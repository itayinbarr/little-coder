"""Harbor (Terminal-Bench 2.0) adapter for little-coder.

Subclasses harbor.agents.base.BaseAgent (the TB 2.0 counterpart of TB 1.0's
terminal_bench.agents.base_agent.BaseAgent). The heavy lifting — pi RPC
subprocess, extension stack, ShellSession proxy — is shared with the TB 1.0
adapter via benchmarks/rpc_client.py::PiRpc.

The one moving part that differs from TB 1.0:

  TB 1.0:  agent gets a TmuxSession.send_keys(...) interface — sync.
  TB 2.0:  agent gets environment.exec(command, ...) — *async*.

My PiRpc reader thread invokes the shell-proxy callback synchronously when
an extension_ui_request with the __LC_TB_SHELL__ prefix arrives. To call
harbor's async env.exec from that sync context, we stash the event loop
in run() and use asyncio.run_coroutine_threadsafe().

Launch:

    harbor run \
      --dataset terminal-bench@2.0 \
      --agent-import-path benchmarks.harbor_adapter.little_coder_agent:LittleCoderAgent \
      --model llamacpp/qwen3.6-35b-a3b \
      --n-concurrent 1
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import sys
import uuid
from pathlib import Path


def _read_version_from_package_json() -> str:
    """Read agent version from the repo's package.json at import time.

    Avoids hardcoded version drift between the adapter's version() return
    and the actual released tag. Falls back to "unknown" if the file is
    missing or malformed.
    """
    try:
        pkg = Path(__file__).resolve().parents[2] / "package.json"
        return json.load(open(pkg)).get("version", "unknown")
    except Exception:
        return "unknown"


_AGENT_VERSION = _read_version_from_package_json()


from harbor.agents.base import BaseAgent
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext

# benchmarks/ isn't a package — let the importer resolve by sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from rpc_client import PiRpc  # noqa: E402


DEFAULT_ALLOWED_TOOLS = ["ShellSession", "ShellSessionCwd", "ShellSessionReset"]
DEFAULT_MODEL = "llamacpp/qwen3.6-35b-a3b"

# Same line-dedup + ANSI-strip + truncation used by the TB 1.0 adapter so
# output-format consistency is preserved across benchmarks.
ANSI_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
MAX_LINES = 200


def _strip_ansi(s: str) -> str:
    return ANSI_RE.sub("", s or "")


def _format_output(stdout: str, stderr: str, code: int, cwd: str, timed_out: bool) -> str:
    raw = (stdout or "") + (("\n[stderr]\n" + stderr) if stderr else "")
    cleaned = _strip_ansi(raw).replace("\r", "")
    lines = cleaned.split("\n")
    # dedup
    deduped, last, dup = [], None, 0
    for ln in lines:
        if ln == last:
            dup += 1; continue
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
        head, tail = MAX_LINES // 2, MAX_LINES // 4
        skipped = len(deduped) - head - tail
        deduped = deduped[:head] + [f"  [... {skipped} lines truncated ...]"] + deduped[-tail:]
        truncated = True
    body = "\n".join(deduped)
    bits = [f"exit={code}", f"cwd={cwd}", f"timed_out={'true' if timed_out else 'false'}"]
    if truncated: bits.append("output_truncated=true")
    bits.append("backend=harbor-env")
    footer = "[" + " ".join(bits) + "]"
    return f"{body}\n{footer}" if body else footer


class _HarborShellProxy:
    """Stateful shell proxy over harbor's BaseEnvironment.exec().

    harbor's env.exec() is stateless — each call is a fresh shell. To give
    little-coder's ShellSession tool the persistent-cwd / persistent-env
    semantics it expects, we track cwd in the proxy and prepend `cd <cwd>`
    to each command. `pwd` is echoed after the user command so we can
    capture the possibly-updated cwd for the next call.
    """

    def __init__(self, environment: BaseEnvironment, loop: asyncio.AbstractEventLoop, logger: logging.Logger):
        self.env = environment
        self.loop = loop
        self.logger = logger
        self.cwd = "/app"  # TB 2.0 convention — overridden by first `pwd`

    async def _exec_async(self, command: str, timeout: int) -> str:
        sentinel = f"__LC_END_{uuid.uuid4().hex[:8]}__"
        wrapped = f"cd {self.cwd} 2>/dev/null; {{ {command} ; }} ; __rc=$? ; printf '\\n{sentinel}:%d:' $__rc ; pwd"
        try:
            result = await self.env.exec(command=wrapped, timeout_sec=timeout)
        except asyncio.TimeoutError:
            return _format_output("", "command timed out", -1, self.cwd, True)
        except Exception as e:
            return _format_output("", f"env.exec error: {e}", -1, self.cwd, False)

        out = result.stdout or ""
        err = result.stderr or ""
        # Peel sentinel to recover exit code + new cwd
        marker = out.rfind(sentinel + ":")
        code = result.return_code if result.return_code is not None else 0
        if marker >= 0:
            tail = out[marker + len(sentinel) + 1:]
            parts = tail.split(":", 1)
            try: code = int(parts[0])
            except (ValueError, IndexError): pass
            if len(parts) > 1:
                cwd_line = parts[1].lstrip("\r\n").split("\n")
                if cwd_line and cwd_line[0].strip():
                    self.cwd = cwd_line[0].strip()
            out = out[:marker].rstrip()
        return _format_output(out, err, code, self.cwd, False)

    def run(self, command: str, timeout: int) -> str:
        """Sync entry point called by PiRpc's reader thread."""
        fut = asyncio.run_coroutine_threadsafe(self._exec_async(command, timeout), self.loop)
        try:
            return fut.result(timeout=timeout + 30)
        except Exception as e:
            return _format_output("", f"shell proxy error: {e}", -1, self.cwd, False)

    def reset(self) -> str:
        self.cwd = "/app"
        return f"shell reset (cwd → /app)"


class LittleCoderAgent(BaseAgent):
    """Harbor (TB 2.0) adapter for little-coder (v0.1.0+ pi port)."""

    SUPPORTS_ATIF = False

    @staticmethod
    def name() -> str:
        return "little-coder"

    def version(self) -> str | None:
        return _AGENT_VERSION

    async def setup(self, environment: BaseEnvironment) -> None:
        # little-coder runs pi on the host; no in-container setup needed.
        # The environment is used only for command proxying during run().
        pass

    async def run(
        self,
        instruction: str,
        environment: BaseEnvironment,
        context: AgentContext,
    ) -> None:
        model = self.model_name or DEFAULT_MODEL
        session_id = f"hb-{uuid.uuid4().hex[:10]}"

        loop = asyncio.get_running_loop()
        proxy = _HarborShellProxy(environment, loop, self.logger)

        def tb_shell_handler(payload: dict) -> str:
            op = payload.get("op")
            if op == "run":
                return proxy.run(payload.get("command", ""), int(payload.get("timeout", 30)))
            if op == "reset":
                return proxy.reset()
            return f"Error: unknown ShellSession op '{op}'"

        prompt = (
            "You are solving a Terminal-Bench 2.0 task inside a Linux container.\n"
            "The ONLY way to interact with the container is the ShellSession tool; "
            "its cwd persists between calls (tracked by the adapter).\n"
            "Default working directory is /app.\n"
            "File tools like Read/Write/Edit are NOT available — use shell commands "
            "(cat, sed -i, heredoc 'cat > file <<EOF') through ShellSession instead.\n\n"
            f"TASK:\n{instruction}\n\n"
            "When the task is complete, stop calling tools and say 'done'."
        )

        log_path = self.logs_dir / "little_coder.log"
        log_fh = log_path.open("w") if self.logs_dir else None

        try:
            # PiRpc spawns pi --mode rpc and wires the shell proxy. The reader
            # thread invokes tb_shell_handler synchronously; the handler
            # bridges to this event loop via run_coroutine_threadsafe.
            rpc = await asyncio.to_thread(
                PiRpc,
                model=model,
                cwd=str(Path.cwd()),
                benchmark="terminal_bench",
                allowed_tools=DEFAULT_ALLOWED_TOOLS,
                session_id=session_id,
                tb_mode=True,
                max_turns=40,
                tb_shell_handler=tb_shell_handler,
            )
            try:
                result = await asyncio.to_thread(rpc.prompt_and_collect, prompt, 3600)
                stop_reason = getattr(result, "stop_reason", "unknown")
                if log_fh:
                    # Distinguishes a crashed pi from a model that ran long;
                    # both used to look identical here.
                    log_fh.write(f"=== stop_reason: {stop_reason} ===\n")
                    log_fh.write(f"=== assistant text ===\n{result.assistant_text}\n\n")
                    for tc in result.tool_calls:
                        log_fh.write(f">> {tc['name']}({tc.get('args', {})})\n")
                        preview = (tc.get("result_text", "") or "")[:400]
                        log_fh.write(f"<< {preview}\n")
                    notes = rpc.notifications() if hasattr(rpc, "notifications") else []
                    if notes:
                        log_fh.write(f"\n=== pi notifications ({len(notes)}) ===\n")
                        for n in notes:
                            log_fh.write(f"[{n.get('notifyType','info')}] {n.get('message','')}\n")
                    stderr = rpc.stderr()
                    if stderr:
                        log_fh.write(f"\n=== pi stderr ===\n{stderr}\n")
                # Harbor's AgentContext: populate what we can. Token usage
                # isn't currently plumbed through pi-ai; leave None.
                context.metadata = {
                    "stop_reason": stop_reason,
                    "n_tool_calls": len(result.tool_calls),
                    "n_turns": result.turn_count,
                    "n_compactions": result.compaction_events,
                    "n_notifications": len(rpc.notifications()) if hasattr(rpc, "notifications") else 0,
                    "little_coder_version": self.version(),
                    "benchmark": "terminal_bench_2.0",
                }
            finally:
                await asyncio.to_thread(rpc.close, 3)
        except Exception as e:
            self.logger.error(f"LittleCoderAgent run failed: {e}")
            if log_fh:
                log_fh.write(f"\nAGENT ERROR: {e}\n")
            raise
        finally:
            if log_fh:
                log_fh.flush()
                log_fh.close()
