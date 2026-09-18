import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { SHELL_TOOLS, detectWriteTargets, splitCommandChain } from "../_shared/shell-write.ts";
import { createEditConfirmer } from "./manual-edit-confirm.ts";

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
  // No-ops. `cmd 2>/dev/null || true` is the standard way to make a probe not
  // fail a chain, and refusing it made the model think the probe itself was
  // the problem (@guppy42 on #94: "it seem to believe that it got denied
  // because of ls"). Neither builtin can do anything.
  "true", "false",
];

// ── the interpreter hole (issue #94) ───────────────────────────────────────
//
// `python `, `python3 `, `node `, `ruby `, `perl ` are on the whitelist because
// running a SCRIPT is what benchmark work and ordinary development need. But a
// prefix allowlist cannot survive a general-purpose interpreter invoked with an
// inline-code flag, and four separate reporters watched their models discover
// that: `python3 -c "import os; os.remove(...)"`, `node -e
// "require('fs').unlinkSync(...)"`, `env bash -c 'rm x'`. The refusal message
// added in v1.16.0 stopped most of the *searching* (the tokens saved were the
// expensive half), but the door itself stayed open to any model that chose to
// walk through it.
//
// This is the narrow fix: the interpreters stay whitelisted for running files,
// and the inline-code forms are refused. `python3 solution.py` works;
// `python3 -c "..."` does not.
//
// It is still not a sandbox, and nothing here should be read as claiming
// otherwise: `python3 evil.py` is one `write` away, and that is a boundary a
// prefix list can never draw. What it does is stop the guard from being
// trivially side-stepped by a model that has just been told no.

/** Split one command segment into argv-ish words, respecting single and double
 *  quotes so a flag inside a quoted string is not mistaken for a real one
 *  (`python3 app.py "--dry-run -c"` passes two words, not four). */
export function tokenizeSegment(segment: string): string[] {
  const out: string[] = [];
  let cur = "";
  let quote: string | null = null;
  let esc = false;
  let started = false;
  for (const ch of segment) {
    if (esc) {
      cur += ch;
      esc = false;
      started = true;
      continue;
    }
    if (ch === "\\") {
      esc = true;
      started = true;
      continue;
    }
    if (quote) {
      if (ch === quote) quote = null;
      else cur += ch;
      started = true;
      continue;
    }
    if (ch === "'" || ch === '"') {
      quote = ch;
      started = true;
      continue;
    }
    if (/\s/.test(ch)) {
      if (started) out.push(cur);
      cur = "";
      started = false;
      continue;
    }
    cur += ch;
    started = true;
  }
  if (started) out.push(cur);
  return out;
}

/** Interpreter → the flags that make it execute code from the command line
 *  instead of from a file. `node -p` / `--print` is `--eval` that also prints,
 *  and perl's `-E` is `-e` with newer features enabled; both are the same hole. */
const INLINE_CODE_FLAGS: Record<string, readonly string[]> = {
  python: ["-c"],
  python2: ["-c"],
  python3: ["-c"],
  node: ["-e", "--eval", "-p", "--print"],
  nodejs: ["-e", "--eval", "-p", "--print"],
  ruby: ["-e"],
  perl: ["-e", "-E"],
};

/** `find` actions that run commands or delete/write files. `find` is on the
 *  whitelist as a SEARCH tool; `find . -name x -delete` is not a search. */
const FIND_ACTIONS = new Set(["-exec", "-execdir", "-ok", "-okdir", "-delete", "-fprint", "-fprintf", "-fls"]);

/** `sed` in-place flags. `sed` is whitelisted for reading a stream; `sed -i`
 *  rewrites the file on disk, which write-guard never sees because there is no
 *  redirect to detect. */
function isSedInPlace(tok: string): boolean {
  // -i, -i.bak, --in-place, --in-place=.bak
  return tok === "-i" || tok.startsWith("-i.") || tok === "--in-place" || tok.startsWith("--in-place=");
}

/**
 * The reason one segment must be refused despite matching a safe prefix, or
 * null when there is none.
 *
 * Returned as a string rather than a boolean because the refusal message is the
 * part that actually changes model behaviour (v1.16.0's lesson): "python3 -c
 * runs arbitrary code" tells it what to do differently; "refused" does not.
 */
export function unsafeInvocation(segment: string): string | null {
  const words = tokenizeSegment(segment);
  if (words.length === 0) return null;
  // `env FOO=1 python3 -c ...` hides the real command behind env, which is
  // whitelisted for printing the environment. Step past the assignments and
  // judge what env is actually launching (@Franck-Nein watched a model settle
  // on `env bash -c` and never go back to plain commands).
  let i = 0;
  if (words[0] === "env" || words[0] === "/usr/bin/env") {
    i = 1;
    while (i < words.length && (/^[A-Za-z_][A-Za-z0-9_]*=/.test(words[i]) || words[i] === "-i" || words[i] === "--ignore-environment")) i++;
    if (i < words.length) {
      return (
        `"env" was used to launch "${words[i]}". env is whitelisted for printing the environment, not for ` +
        `starting another command through it. Running a command this way is how a refusal gets worked around, ` +
        `not how it gets fixed.`
      );
    }
    return null; // bare `env` (or env with only assignments) just prints
  }

  const binary = (words[i].split("/").pop() ?? words[i]).toLowerCase();
  const inline = INLINE_CODE_FLAGS[binary];
  if (inline) {
    // Flags precede the script path, so stop at the first non-flag word: that
    // is the file being run, and everything after it belongs to the script.
    for (let j = i + 1; j < words.length; j++) {
      const w = words[j];
      if (!w.startsWith("-")) break;
      if (w === "--") break;
      if (inline.includes(w)) {
        return (
          `"${binary} ${w}" runs code written on the command line, which is not what "${binary}" is on the ` +
          `whitelist for. Running a SCRIPT is (\`${binary} script.py\`). Inline code can do anything, including ` +
          `the thing that was just refused, so it is refused too.`
        );
      }
    }
    return null;
  }

  if (binary === "find") {
    for (let j = i + 1; j < words.length; j++) {
      if (FIND_ACTIONS.has(words[j])) {
        return (
          `"find ${words[j]}" runs a command or deletes files. find is whitelisted for SEARCHING; use it to ` +
          `locate the files and then act on them with a tool that is allowed to.`
        );
      }
    }
    return null;
  }

  if (binary === "sed") {
    for (let j = i + 1; j < words.length; j++) {
      if (words[j] === "--") break;
      if (isSedInPlace(words[j])) {
        return (
          `"sed ${words[j]}" rewrites the file in place. sed is whitelisted for reading a stream; use the edit ` +
          `tool to change a file, which shows the diff and does not need a shell at all.`
        );
      }
    }
    return null;
  }

  return null;
}

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
 *
 * And a third, from issue #94: **matching a prefix is not enough.** The
 * interpreters are on the list so that scripts can be run, and a model that has
 * just been refused reaches for `python3 -c "import os; os.remove(...)"`, which
 * the prefix test waves straight through. `unsafeInvocation` refuses the
 * inline-code form of an otherwise-whitelisted binary.
 */
export function isSafeBash(command: string, prefixes: readonly string[] = getSafePrefixes()): boolean {
  if (detectWriteTargets(command).length > 0) return false;
  const segments = splitCommandChain(command);
  if (segments.length === 0) return false;
  return segments.every(
    (segment) => prefixes.some((p) => segment.startsWith(p)) && unsafeInvocation(segment) === null,
  );
}

/** The first segment's reason for being unsafe, for the refusal message. */
export function firstUnsafeInvocation(command: string): string | null {
  for (const segment of splitCommandChain(command)) {
    const reason = unsafeInvocation(segment);
    if (reason) return reason;
  }
  return null;
}

// Which tools count as "hands a string to a shell" lives in _shared, so this
// gate and write-guard can never disagree about it again (issue #70).

function getPermissionMode(): "auto" | "accept-all" | "manual" {
  const v = process.env.LITTLE_CODER_PERMISSION_MODE;
  if (v === "accept-all" || v === "manual") return v;
  return "auto";
}

const WRITE_TOOLS = new Set(["write", "edit"]);

export default function (pi: ExtensionAPI) {
  const editConfirmer = createEditConfirmer();
  pi.on("tool_call", async (event, ctx) => {
    const mode = getPermissionMode();
    if (mode === "accept-all") return;

    const toolName = (event as any).toolName;
    const input: any = (event as any).input ?? (event as any).args;

    if (WRITE_TOOLS.has(toolName)) {
      if (mode === "manual") {
        if ((await editConfirmer.confirm(ctx, String(toolName), input)) === "deny") {
          return { block: true, reason: "edit cancelled by user" };
        }
      }
      return;
    }

    if (SHELL_TOOLS.has(toolName)) {
      const cmd = input?.command;
      if (typeof cmd === "string") {
        if (mode === "manual") {
          const confirmed = await ctx.ui.confirm(
            `About to execute:\n\n${cmd}`,
            "Execute this command?",
          );
          if (!confirmed) {
            return { block: true, reason: "command cancelled by user" };
          }
          return;
        }
        if (!isSafeBash(cmd)) {
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
          // Issue #94: a whitelisted binary used in a way the whitelist never
          // meant to allow. This message has to explain the DISTINCTION (the
          // binary is allowed, this use of it is not), or the model reads it as
          // "python is blocked" and starts hunting for another interpreter,
          // which is the loop the whole refusal rewrite exists to stop.
          const unsafe = firstUnsafeInvocation(cmd);
          if (unsafe) {
            return {
              block: true,
              reason:
                `shell whitelist: ${unsafe}\n` +
                `Do NOT reach for a different interpreter or an -exec flag to get the same effect. That ` +
                `defeats a limit the user set on purpose, and wastes your budget.\n` +
                `If a file needs changing, use edit/write, which do not need a shell. If this genuinely needs ` +
                `to run, tell the user it was refused and that they can allow it with ` +
                `LITTLE_CODER_PERMISSION_MODE=accept-all, then continue with the rest of the task.`,
            };
          }
          const offender =
            splitCommandChain(cmd).find((s) => !isSafeBash(s)) ?? cmd;
          const binary = offender.split(/\s+/)[0];
          // Say what to do next, not just what was refused.
          //
          // The bare "not in SAFE_PREFIXES" line sent models hunting: observed
          // live, a refusal on `./build.sh` was followed by `bash ./build.sh`,
          // then `sh ./build.sh`, then a successful `python3 -c
          // "subprocess.run(...)"` — three wasted turns and the guard defeated
          // anyway, because interpreters are themselves whitelisted (issue #94).
          // A refusal that names the actual remedy is the only thing that stops
          // the search, and it is far closer to the decision than a line in
          // AGENTS.md thousands of tokens earlier.
          return {
            block: true,
            reason:
              `shell whitelist: "${binary}" is not in SAFE_PREFIXES, so this command was refused.\n` +
              `Do NOT try to reach the same effect another way — re-running it through ` +
              `python3 -c, node -e, env, sh, or an -exec flag defeats a limit the user set on ` +
              `purpose, and wastes your budget.\n` +
              `If a file needs changing, use edit/write, which do not need a shell. ` +
              `Otherwise tell the user this command was refused and that they can allow it with ` +
              `LITTLE_CODER_BASH_ALLOW="${binary}" (or set LITTLE_CODER_PERMISSION_MODE=accept-all), ` +
              `then continue with the rest of the task.`,
          };
        }
      }
    }
  });
}
