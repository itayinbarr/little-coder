import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { detectWriteTargets, splitCommandChain } from "../_shared/shell-write.ts";

// Port of tools.py::_SAFE_PREFIXES + agent.py::_check_permission. Shell
// commands not matching the whitelist are blocked in "auto" mode. In
// "accept-all" mode all commands pass (benchmark runs set this explicitly).
// Write/Edit confirmations are deferred to the TUI's own prompt; we simply
// add an extra guardrail on the shell here to match little-coder's behavior.
//
// Per-deployment customization (issue #15):
//   LITTLE_CODER_PERMISSION_MODE=auto|accept-all|manual
//   LITTLE_CODER_BASH_ALLOW="cmd1,cmd2 sub,..."  extra allow-prefixes,
//                                                merged with the built-in list.
//
// Issue #70: the gate used to match only `bash`/`Bash`, so a model that hit a
// refusal could re-run the same thing through the `ShellSession` tool and land
// in an execSync with no gate at all. Every shell-executing tool is listed in
// SHELL_TOOLS now, and they all go through the same whitelist.

const BUILTIN_SAFE_PREFIXES: readonly string[] = [
  "ls", "cat", "head", "tail", "wc", "pwd", "echo", "printf", "date",
  "which", "type", "env", "printenv", "uname", "whoami", "id",
  "git log", "git status", "git diff", "git show", "git branch",
  "git remote", "git stash list", "git tag",
  "find ", "grep ", "rg ", "ag ", "fd ", "sed ",
  "python ", "python3 ", "node ", "ruby ", "perl ",
  "pip show", "pip list", "npm list", "cargo metadata",
  "df ", "du ", "free ", "top -bn", "ps ",
  "curl -I", "curl --head",
  // Routine filesystem scaffolding. Trailing space = word boundary, so
  // "cp " matches "cp a b" but not "cpufetch". rm stays off the list by
  // design; use LITTLE_CODER_BASH_ALLOW=rm if a deployment needs it.
  "cp ", "mv ", "mkdir ", "touch ",
];

// Trailing whitespace is meaningful — it acts as a word boundary in startsWith
// matching ("find " refuses "findbug"). We only strip leading whitespace so
// callers retain control over that boundary.
export function parseExtraPrefixes(raw: string | undefined): string[] {
  if (!raw) return [];
  return raw
    .split(",")
    .map((s) => s.trimStart())
    .map((s) => (s.length > 0 && s !== " ".repeat(s.length) ? s : ""))
    .filter((s) => s.length > 0);
}

export function getSafePrefixes(): string[] {
  return [...BUILTIN_SAFE_PREFIXES, ...parseExtraPrefixes(process.env.LITTLE_CODER_BASH_ALLOW)];
}

/**
 * True when EVERY command in `command` is whitelisted and none of them writes.
 *
 * Two hardenings over the original `startsWith` check, both from issue #70:
 *
 * 1. **Judge every segment.** The check ran on the raw string, so only the
 *    first command was ever inspected — `ls && rm -rf /` was "safe" because it
 *    starts with `ls`. Each segment of a `&&`/`||`/`;`/`|` chain now has to
 *    match on its own.
 * 2. **A write is never safe.** `cat` is whitelisted, so
 *    `cat > backend/main.py << 'ENDOFFILE'` passed the prefix test outright.
 *    Any command carrying a redirect/tee/dd target is refused regardless of
 *    which binary it starts with; write-guard then decides whether that
 *    particular path may be written.
 */
export function isSafeBash(command: string, prefixes: readonly string[] = getSafePrefixes()): boolean {
  if (detectWriteTargets(command).length > 0) return false;
  const segments = splitCommandChain(command);
  if (segments.length === 0) return false;
  return segments.every((segment) => prefixes.some((p) => segment.startsWith(p)));
}

// Tools that hand a string to a shell. `ShellSessionCwd` / `ShellSessionReset`
// take no command (they run a fixed `pwd` / are a no-op) and stay ungated.
const SHELL_TOOLS = new Set(["bash", "Bash", "ShellSession"]);

function getPermissionMode(): "auto" | "accept-all" | "manual" {
  const v = process.env.LITTLE_CODER_PERMISSION_MODE;
  if (v === "accept-all" || v === "manual") return v;
  return "auto";
}

export default function (pi: ExtensionAPI) {
  pi.on("tool_call", async (event, _ctx) => {
    const mode = getPermissionMode();
    if (mode === "accept-all") return;

    const toolName = (event as any).toolName;
    const input: any = (event as any).input ?? (event as any).args;

    // Only gate shell-family tools; pi has its own confirmation flow for
    // destructive edits via the TUI.
    if (SHELL_TOOLS.has(toolName)) {
      const cmd = input?.command;
      if (typeof cmd === "string" && !isSafeBash(cmd)) {
        if (mode === "manual") {
          return { block: true, reason: "manual permission mode: shell command not pre-approved" };
        }
        // auto: block when not whitelisted. Name the reason precisely — a
        // refusal the model can't interpret just gets retried verbatim.
        const writes = detectWriteTargets(cmd);
        if (writes.length > 0) {
          return {
            block: true,
            reason:
              `shell whitelist: this command writes to ${writes.map((w) => `"${w.path}"`).join(", ")} ` +
              `via shell redirection. Use the Write tool for a new file, or Edit for an existing one — ` +
              `do not redirect into files.`,
          };
        }
        const offender =
          splitCommandChain(cmd).find((s) => !isSafeBash(s)) ?? cmd;
        return {
          block: true,
          reason: `shell whitelist: "${offender.split(/\s+/)[0]}" is not in SAFE_PREFIXES`,
        };
      }
    }
  });
}
