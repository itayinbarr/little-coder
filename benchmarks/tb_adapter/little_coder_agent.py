"""Terminal-Bench BaseAgent adapter for little-coder.

Ported from benchmarks/tb_adapter/little_coder_agent.py in the Python
little-coder. Still a Python class (TB imports it via --agent-import-path),
but internally spawns `pi --mode rpc` and proxies ShellSession calls back
to the TmuxSession over the extension_ui_request channel.
"""
from __future__ import annotations

import os
import re
import sys
import uuid
import base64
from pathlib import Path
from typing import Any

from terminal_bench.agents.base_agent import AgentResult, BaseAgent
from terminal_bench.agents.failure_mode import FailureMode
from terminal_bench.terminal.tmux_session import TmuxSession

# benchmarks/ isn't a package; make imports work when TB points at this file
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rpc_client import PiRpc  # noqa: E402


DEFAULT_ALLOWED_TOOLS = ["ShellSession", "ShellSessionCwd", "ShellSessionReset"]
DEFAULT_MODEL = "llamacpp/qwen3.6-35b-a3b"


# ── tmux command execution (matches shell_session.py::_exec_tmux) ──────────
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
MAX_LINES = 200


def _strip_ansi(s: str) -> str:
    return ANSI_RE.sub("", s)


def _format_output(raw: str, code: int, cwd: str, timed_out: bool, backend_note: str) -> str:
    cleaned = _strip_ansi(raw).replace("\r", "")
    lines = cleaned.split("\n")
    # dedup
    deduped = []
    last, dup = None, 0
    for ln in lines:
        if ln == last:
            dup += 1
            continue
        if dup > 0:
            deduped.append(f"  [... {dup} duplicate line(s) collapsed ...]")
        dup = 0
        deduped.append(ln)
        last = ln
    if dup > 0:
        deduped.append(f"  [... {dup} duplicate line(s) collapsed ...]")
    # truncate
    truncated = False
    if len(deduped) > MAX_LINES:
        head = MAX_LINES // 2
        tail = MAX_LINES // 4
        skipped = len(deduped) - head - tail
        deduped = deduped[:head] + [f"  [... {skipped} lines truncated ...]"] + deduped[-tail:]
        truncated = True
    body = "\n".join(deduped)
    bits = [f"exit={code}", f"cwd={cwd}", f"timed_out={'true' if timed_out else 'false'}"]
    if truncated:
        bits.append("output_truncated=true")
    if backend_note:
        bits.append(backend_note)
    footer = "[" + " ".join(bits) + "]"
    return f"{body}\n{footer}" if body else footer


class _TmuxShellProxy:
    """Routes ShellSession calls from pi back to a TB TmuxSession.

    Matches the Python shell_session.py _exec_tmux strategy: stage the
    command (plus sentinel wrapper) to the container via exec_run, then
    `source` the staged file through tmux. Sentinel parsing recovers
    exit code + cwd even when tmux misbehaves.
    """

    def __init__(self, tmux: TmuxSession, session_id: str):
        self.tmux = tmux
        self.sid = session_id
        self._cursor = 0
        self._initialized = False

    def _init_once(self):
        if self._initialized:
            return
        setup = "export PAGER=cat GIT_PAGER=cat LESS=FRX MANPAGER=cat SYSTEMD_PAGER=cat"
        try:
            self.tmux.send_keys([setup, "Enter"], block=True, max_timeout_sec=5.0)
            pane = self.tmux.capture_pane(capture_entire=True)
            self._cursor = len(pane)
        except Exception:
            self._cursor = 0
        self._initialized = True

    def _stage(self, command: str, script_path: str, sentinel: str) -> bool:
        full = (
            f"{{ {command}; }}\n"
            f"__rc=$?\n"
            f"rm -f {script_path}\n"
            f"printf '\\n{sentinel}:%d:' \"$__rc\"\n"
            f"pwd\n"
        )
        try:
            cmd_b64 = base64.b64encode(full.encode("utf-8", errors="replace")).decode()
            result = self.tmux.container.exec_run(
                ["sh", "-c", f"printf '%s' '{cmd_b64}' | base64 -d > {script_path}"],
            )
            return getattr(result, "exit_code", 0) == 0
        except Exception:
            return False

    def run(self, command: str, timeout: int) -> str:
        self._init_once()
        sentinel = f"__LC_END_{uuid.uuid4().hex[:8]}__"
        script_path = f"/tmp/lc_{sentinel}.sh"
        if not self._stage(command, script_path, sentinel):
            return _format_output(
                "Error: could not stage command to container (exec_run failed).",
                -1, "?", False, "backend=tmux-proxy",
            )
        try:
            self.tmux.send_keys([f"source {script_path}", "Enter"],
                                block=True, max_timeout_sec=float(timeout))
        except Exception:
            pass
        try:
            pane = self.tmux.capture_pane(capture_entire=True)
        except Exception:
            pane = ""

        prev_cursor = self._cursor
        marker = pane.rfind(sentinel + ":")
        if marker < 0:
            body = pane[prev_cursor:] if prev_cursor <= len(pane) else ""
            return _format_output(body.strip(), -1, "?", True, "backend=tmux-proxy")

        tail = pane[marker + len(sentinel) + 1:]
        parts = tail.split(":", 1)
        code = int(parts[0]) if parts and parts[0].isdigit() else -1
        cwd = "?"
        if len(parts) > 1:
            cwd_lines = parts[1].lstrip("\r\n").split("\n")
            if cwd_lines:
                cwd = cwd_lines[0].strip() or "?"

        post = pane.find("\n", marker)
        post = (post + 1) if post >= 0 else len(pane)
        cwd_end = pane.find("\n", post)
        new_cursor = (cwd_end + 1) if cwd_end >= 0 else post

        body_end_line = pane.rfind("\n", 0, marker)
        body_start = prev_cursor if prev_cursor <= marker else 0
        body_end = body_end_line if body_end_line > body_start else marker
        body = pane[body_start:body_end]
        body = re.sub(r";\s*tmux\s+wait\s+-S\s+done\b", "", body)
        first = body.find(sentinel)
        if first >= 0:
            eol = body.find("\n", first)
            body = body[eol + 1:] if eol >= 0 else ""
        body = body.lstrip("\n\r ")
        self._cursor = new_cursor
        return _format_output(body, code, cwd, False, "backend=tmux-proxy")

    def reset(self) -> str:
        try:
            self.tmux.send_keys(["C-c"], block=False, min_timeout_sec=0.2)
            self.tmux.send_keys([":q!", "Enter"], block=False, min_timeout_sec=0.2)
            self.tmux.send_keys(["C-c"], block=False, min_timeout_sec=0.2)
            self.tmux.send_keys(["clear", "Enter"], block=True, max_timeout_sec=3.0)
            pane = self.tmux.capture_pane(capture_entire=True)
            self._cursor = len(pane)
        except Exception:
            pass
        self._initialized = False
        self._init_once()
        return f"Session '{self.sid}' unstuck and reinitialized."


class LittleCoderAgent(BaseAgent):
    """Terminal-Bench adapter for little-coder (v0.1.0+ pi port)."""

    @staticmethod
    def name() -> str:
        # Leaderboard display name — matches the 0.1.0 release. The
        # (agent × model) pair shown on tbench.ai will be
        # "little-coder" × whatever TB_LITTLE_CODER_MODEL resolves to
        # (default llamacpp/qwen3.6-35b-a3b).
        return "little-coder"

    def __init__(
        self,
        model_name: str | None = None,
        allowed_tools: list[str] | None = None,
        max_turns: int | None = 40,
        verbose: bool = False,
        **kwargs,
    ):
        super().__init__(**kwargs)
        self._model = (
            model_name
            or os.environ.get("TB_LITTLE_CODER_MODEL")
            or DEFAULT_MODEL
        )
        self._allowed_tools = allowed_tools or DEFAULT_ALLOWED_TOOLS
        self._max_turns = max_turns
        self._verbose = verbose

    def perform_task(
        self,
        instruction: str,
        session: TmuxSession,
        logging_dir: Path | None = None,
    ) -> AgentResult:
        session_id = f"tb-{uuid.uuid4().hex[:10]}"
        proxy = _TmuxShellProxy(session, session_id)

        def tb_shell_handler(payload: dict) -> str:
            op = payload.get("op")
            if op == "run":
                return proxy.run(payload.get("command", ""), int(payload.get("timeout", 30)))
            if op == "reset":
                return proxy.reset()
            return f"Error: unknown ShellSession op '{op}'"

        failure = FailureMode.NONE
        text_out = ""
        total_in, total_out = 0, 0
        turns = 0

        log_fh = None
        if logging_dir is not None:
            logging_dir.mkdir(parents=True, exist_ok=True)
            log_fh = (logging_dir / "little_coder.log").open("w")

        prompt = (
            "You are solving a Terminal-Bench task inside a Linux container.\n"
            "The ONLY way to interact with the container is the ShellSession tool; "
            "its cwd, env vars, and shell state persist between calls.\n"
            "You are running as root in the container; /app is writable.\n"
            "File tools like Read/Write/Edit are NOT available — use shell commands "
            "(cat, sed -i, heredoc 'cat > file <<EOF') through ShellSession instead.\n\n"
            f"TASK:\n{instruction}\n\n"
            "When the task is complete, stop calling tools and say 'done'."
        )

        try:
            with PiRpc(
                model=self._model,
                cwd=str(Path.cwd()),
                benchmark="terminal_bench",
                allowed_tools=self._allowed_tools,
                session_id=session_id,
                tb_mode=True,
                max_turns=self._max_turns,
                tb_shell_handler=tb_shell_handler,
            ) as rpc:
                result = rpc.prompt_and_collect(prompt, timeout=3600)
                text_out = result.assistant_text
                turns = result.turn_count
                if log_fh:
                    # Distinguishes a crashed pi from a model that simply ran
                    # long; both used to look identical in this log.
                    log_fh.write(
                        f"=== stop_reason: {getattr(result, 'stop_reason', 'unknown')} ===\n")
                    log_fh.write(f"=== assistant text ===\n{text_out}\n\n")
                    for tc in result.tool_calls:
                        log_fh.write(f">> {tc['name']}({tc.get('args', {})})\n")
                        preview = (tc.get("result_text", "") or "")[:400]
                        log_fh.write(f"<< {preview}\n")
                    # Extension notifications: per-turn evidence of
                    # skill-inject / knowledge-inject / thinking-budget /
                    # quality-monitor / turn-cap firing. Structured as one
                    # line per event so tb_status.sh can grep/aggregate.
                    notes = rpc.notifications() if hasattr(rpc, "notifications") else []
                    if notes:
                        log_fh.write(f"\n=== pi notifications ({len(notes)}) ===\n")
                        for n in notes:
                            log_fh.write(f"[{n.get('notifyType','info')}] {n.get('message','')}\n")
                    stderr = rpc.stderr()
                    if stderr:
                        log_fh.write(f"\n=== pi stderr ===\n{stderr}\n")
        except Exception as e:
            failure = FailureMode.UNKNOWN_AGENT_ERROR
            if log_fh:
                log_fh.write(f"\nAGENT ERROR: {e}\n")
        finally:
            if log_fh:
                log_fh.flush()
                log_fh.close()

        return AgentResult(
            total_input_tokens=total_in,
            total_output_tokens=total_out,
            failure_mode=failure,
        )
