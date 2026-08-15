import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "@sinclair/typebox";
import { execSync } from "node:child_process";
import { formatOutput, DEFAULT_TIMEOUT } from "./helpers.ts";

// Port of local/tools/shell_session.py. Two backends implemented:
//   1. tmux-proxy — when LITTLE_CODER_TB_MODE=1, route every command to the
//      parent TB adapter over the extension_ui_request channel. The parent
//      drives the actual TmuxSession so commands appear in TB's trajectory.
//   2. subprocess — child_process.execSync for local use (GAIA doesn't use
//      ShellSession; this is for local REPL + debugging of TB adapter).
//
// The sentinel-prompt pexpect backend from the Python version (persistent
// bash process with state between calls) is deliberately skipped because
// neither Terminal-Bench nor GAIA requires it; TB uses tmux, GAIA uses Bash.

const TB_MODE_ENV = "LITTLE_CODER_TB_MODE";
const TB_PROXY_PREFIX = "__LC_TB_SHELL__:";

function inTbMode(): boolean {
  return process.env[TB_MODE_ENV] === "1";
}

async function execSubprocess(command: string, timeoutSec: number): Promise<string> {
  try {
    const buf = execSync(command, {
      shell: "/bin/bash",
      timeout: timeoutSec * 1000,
      encoding: "utf-8",
      maxBuffer: 10 * 1024 * 1024,
    });
    return formatOutput(String(buf), 0, process.cwd(), false, "backend=subprocess");
  } catch (err: any) {
    const out = (err.stdout?.toString?.() ?? "") + (err.stderr?.toString?.() ?? "");
    const timedOut = err.code === "ETIMEDOUT" || err.signal === "SIGTERM";
    const code = typeof err.status === "number" ? err.status : -1;
    return formatOutput(out, code, process.cwd(), timedOut, "backend=subprocess");
  }
}

async function execTmuxProxy(
  ctx: any,
  command: string,
  timeoutSec: number,
  sessionId: string,
): Promise<string> {
  const payload = {
    op: "run",
    session_id: sessionId,
    command,
    timeout: timeoutSec,
  };
  // Use ctx.ui.input as a generic data-carrying channel. The Python TB adapter
  // intercepts extension_ui_request with title prefix __LC_TB_SHELL__ and
  // responds with the formatted tool output string.
  const title = TB_PROXY_PREFIX + JSON.stringify(payload);
  const response = await ctx.ui.input(title, "");
  if (typeof response === "string") return response;
  return formatOutput(
    "Error: tmux proxy returned no response",
    -1, "?", true, "backend=tmux-proxy",
  );
}

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "ShellSession",
    label: "ShellSession",
    // The description is computed, because the two backends genuinely differ
    // and one sentence cannot honestly cover both. Under Terminal-Bench a real
    // tmux session is driven, so state does persist. Locally the backend is
    // execSync — one process per call, no shared cwd, no shared env — and the
    // tool spent every release until v1.16.0 telling local users the opposite,
    // so a `cd` "worked" and then silently did not apply to the next call.
    description: inTbMode()
      ? "Run a command in a persistent bash session. cd, env vars, and shell state " +
        "persist across calls. One command per turn. Default timeout 30s (increase to " +
        "120-300 for installs/builds). Output is line-capped with head/tail truncation " +
        "and a trailing [exit=N cwd=… timed_out=…] footer."
      : "Run a shell command. NOTE: each call runs in its own process — cd, env vars, " +
        "and shell state do NOT persist between calls, so use absolute paths and set " +
        "variables inline. Blocks until the command exits: for anything long-running " +
        "(training, builds, servers) use ShellStart instead. Default timeout 30s " +
        "(increase to 120-300 for installs/builds). Output is line-capped with " +
        "head/tail truncation and a trailing [exit=N cwd=… timed_out=…] footer.",
    parameters: Type.Object({
      command: Type.String({ description: "Shell command to run" }),
      timeout: Type.Optional(Type.Integer({ description: "Seconds (default 30, max 600)" })),
    }),
    async execute(_id, params, _signal, _onUpdate, ctx) {
      const cmd = String(params.command ?? "").trim();
      if (!cmd) {
        return {
          content: [{ type: "text", text: "Error: command is required" }],
          details: {}, isError: true,
        };
      }
      const rawTimeout = typeof params.timeout === "number" ? params.timeout : DEFAULT_TIMEOUT;
      const timeoutSec = Math.max(5, Math.min(rawTimeout, 600));
      const sessionId = process.env.LITTLE_CODER_SESSION_ID || "default";

      let text: string;
      if (inTbMode()) {
        text = await execTmuxProxy(ctx, cmd, timeoutSec, sessionId);
      } else {
        text = await execSubprocess(cmd, timeoutSec);
      }
      return { content: [{ type: "text", text }], details: {} };
    },
  });

  pi.registerTool({
    name: "ShellSessionCwd",
    label: "ShellSessionCwd",
    description: "Print the current working directory of the shell session.",
    parameters: Type.Object({}),
    async execute(_id, _params, _signal, _onUpdate, ctx) {
      const sessionId = process.env.LITTLE_CODER_SESSION_ID || "default";
      let text: string;
      if (inTbMode()) {
        text = await execTmuxProxy(ctx, "pwd", 5, sessionId);
      } else {
        text = await execSubprocess("pwd", 5);
      }
      return { content: [{ type: "text", text }], details: {} };
    },
  });

  pi.registerTool({
    name: "ShellSessionReset",
    label: "ShellSessionReset",
    description: inTbMode()
      ? "Kill and restart the bash session. Use only if it becomes unresponsive."
      : "No-op locally: the subprocess backend keeps no state to reset.",
    parameters: Type.Object({}),
    async execute(_id, _params, _signal, _onUpdate, ctx) {
      const sessionId = process.env.LITTLE_CODER_SESSION_ID || "default";
      if (inTbMode()) {
        const payload = { op: "reset", session_id: sessionId };
        await ctx.ui.input(TB_PROXY_PREFIX + JSON.stringify(payload), "");
        return {
          content: [{ type: "text", text: `Session '${sessionId}' unstuck and reinitialized.` }],
          details: {},
        };
      }
      // Subprocess backend is stateless — reset is a no-op
      return {
        content: [{ type: "text", text: `Session '${sessionId}' reset (subprocess backend is stateless).` }],
        details: {},
      };
    },
  });
}
