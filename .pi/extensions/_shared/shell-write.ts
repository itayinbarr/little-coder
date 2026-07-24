// Shell command analysis for the write/permission guards (issue #70).
//
// Background: little-coder refuses `write` on an existing file so small models
// are pushed to `Edit` instead of rewriting whole files, and it whitelists bash
// commands. Both guards matched on tool NAME — write-guard on `write`,
// permission-gate on `bash` — so once `write` got refused, the model could
// reach the same bytes through a shell:
//
//     cat > backend/main.py << 'ENDOFFILE'
//     … whole file …
//     ENDOFFILE
//
// rvanswieten saw exactly that 5x in one session. And `ShellSession` hit
// neither guard at all. The bash whitelist wouldn't have caught it either:
// `isSafeBash` was `startsWith` on the raw string, and "cat" is whitelisted —
// with no awareness of the `>` sitting right after it.
//
// Matching on the heredoc delimiter would be trivially routed around with a
// different delimiter, so this module looks at what actually writes: shell
// redirection. Everything here is pure and string-only so it can be unit
// tested without a shell.
//
// This dir has no `index.ts` on purpose — the launcher's extension discovery
// requires one, so `_shared` is skipped and stays a plain library.

/** An operator/keyword through which a command writes to a path. */
export type WriteKind = "redirect" | "append" | "tee" | "dd";

export interface ShellWrite {
  /** The (possibly relative) path the command writes to. */
  path: string;
  kind: WriteKind;
}

// Operators that chain one command into the next. Splitting on these lets the
// whitelist judge every segment rather than only the first one, so
// `ls && rm -rf /` can't ride in on `ls`.
const CHAIN_OPERATORS = ["&&", "||", ";", "|", "\n"];

/**
 * Walk `cmd` once, tracking quote state, and hand each character to `visit`.
 *
 * Quote tracking is what keeps every consumer here from firing on text that
 * merely looks like shell syntax — `grep "a > b" file` writes nothing. A
 * backslash escape outside single quotes hides the next character too.
 */
function scan(
  cmd: string,
  visit: (ch: string, index: number, quoted: boolean) => void,
): void {
  let quote: '"' | "'" | null = null;
  for (let i = 0; i < cmd.length; i++) {
    const ch = cmd[i];
    if (quote === null && ch === "\\") {
      i++; // skip the escaped character entirely
      continue;
    }
    if (quote === "'" && ch === "\\") {
      // Backslash is literal inside single quotes — no escaping happens.
      visit(ch, i, true);
      continue;
    }
    if (quote === null && (ch === '"' || ch === "'")) {
      quote = ch;
      continue;
    }
    if (quote !== null && ch === quote) {
      quote = null;
      continue;
    }
    visit(ch, i, quote !== null);
  }
}

// `<< DELIM`, `<<-DELIM`, `<<'DELIM'`, `<<"DELIM"`. `<<<` is a here-string
// (single-line data, no body to strip) and must not match, hence the guard on
// a third `<` at the call site.
const HEREDOC_START = /<<-?[ \t]*(?:'([^']*)'|"([^"]*)"|([A-Za-z_][A-Za-z0-9_]*))/;

/**
 * Remove heredoc bodies, leaving the command line that opened them.
 *
 * A heredoc body is data, not shell syntax, and analyzing it produces noise in
 * both directions: a `>` in the payload (`if a > b:`) looks like a redirect,
 * and an apostrophe (`don't`) leaves the quote scanner stuck mid-string for
 * everything after it. The redirect we actually care about — the `>` in
 * `cat > main.py << 'EOF'` — always sits on the opening line, so dropping the
 * body loses nothing and removes every one of those false readings.
 */
export function stripHeredocBodies(cmd: string): string {
  let out = cmd;
  let searchFrom = 0;
  // One pass per heredoc; a command can open several.
  for (let guard = 0; guard < 32; guard++) {
    const rest = out.slice(searchFrom);
    const m = HEREDOC_START.exec(rest);
    if (!m || m.index === undefined) break;
    const at = searchFrom + m.index;
    if (out[at + 2] === "<") {
      // `<<<` here-string — nothing to strip, keep scanning past it.
      searchFrom = at + 3;
      continue;
    }
    const delim = m[1] ?? m[2] ?? m[3] ?? "";
    const bodyStart = out.indexOf("\n", at + m[0].length);
    if (bodyStart === -1 || !delim) {
      // Body never started (single-line command) — nothing to remove.
      searchFrom = at + m[0].length;
      continue;
    }
    const lines = out.slice(bodyStart + 1).split("\n");
    let consumed = 0;
    let closed = false;
    for (const line of lines) {
      consumed += line.length + 1;
      // `<<-` allows the terminator to be indented with tabs.
      if (line.trim() === delim) {
        closed = true;
        break;
      }
    }
    const bodyEnd = closed
      ? Math.min(bodyStart + consumed, out.length)
      : out.length; // unterminated heredoc: the rest of the string is body
    out = out.slice(0, at) + out.slice(bodyEnd);
    searchFrom = at;
  }
  return out;
}

/**
 * Split a command line into the individual commands it runs, on unquoted
 * `&&`, `||`, `;`, `|` and newlines. Heredoc bodies are stripped first so
 * their contents are never mistaken for commands.
 */
export function splitCommandChain(raw: string): string[] {
  const cmd = stripHeredocBodies(raw);
  const cuts: Array<{ at: number; len: number }> = [];
  scan(cmd, (_ch, i, quoted) => {
    if (quoted) return;
    for (const op of CHAIN_OPERATORS) {
      if (cmd.startsWith(op, i)) {
        // Don't cut inside an already-recorded operator (`&&` must not also
        // match as two separate cuts).
        const last = cuts[cuts.length - 1];
        if (last && i < last.at + last.len) return;
        cuts.push({ at: i, len: op.length });
        return;
      }
    }
  });

  const segments: string[] = [];
  let start = 0;
  for (const cut of cuts) {
    segments.push(cmd.slice(start, cut.at));
    start = cut.at + cut.len;
  }
  segments.push(cmd.slice(start));
  return segments.map((s) => s.trim()).filter((s) => s.length > 0);
}

// `2>`, `>&2`, `&>`, `1>&2` … — file-descriptor plumbing, not a file write.
// We only care about a redirect whose target is a path.
function isFdTarget(target: string): boolean {
  return target.startsWith("&");
}

/**
 * Every path `cmd` writes to via shell redirection or a write-by-design tool.
 *
 * Covers `>`, `>>`, `tee` (with `-a`), and `dd of=`. Ignores fd duplication
 * (`2>&1`, `>&2`), process substitution (`>(…)`), here-strings/heredocs
 * (`<<`, `<<<` — those read), and anything inside quotes.
 *
 * Returns [] for a command that only reads, which is the common case, so
 * callers can treat a non-empty result as "this touches the filesystem".
 */
export function detectWriteTargets(raw: string): ShellWrite[] {
  const cmd = stripHeredocBodies(raw);
  const writes: ShellWrite[] = [];
  const redirects: Array<{ at: number; kind: WriteKind }> = [];

  scan(cmd, (ch, i, quoted) => {
    if (quoted || ch !== ">") return;
    // `>>` — record once, on the first angle bracket.
    if (cmd[i - 1] === ">") return;
    // `<>` opens read-write; treat as a write.
    const append = cmd[i + 1] === ">";
    redirects.push({ at: i + (append ? 2 : 1), kind: append ? "append" : "redirect" });
  });

  for (const { at, kind } of redirects) {
    const rest = cmd.slice(at);
    // Process substitution `>(cmd)` is not a file target.
    if (rest.trimStart().startsWith("(")) continue;
    const target = firstWord(rest);
    if (!target || isFdTarget(target)) continue;
    writes.push({ path: unquote(target), kind });
  }

  for (const segment of splitCommandChain(cmd)) {
    const words = splitWords(segment);
    if (words.length === 0) continue;

    // `tee [-a] FILE…` writes every non-flag argument.
    if (words[0] === "tee") {
      for (const w of words.slice(1)) {
        if (w.startsWith("-")) continue;
        writes.push({ path: unquote(w), kind: "tee" });
      }
    }

    // `dd if=… of=PATH`
    if (words[0] === "dd") {
      for (const w of words.slice(1)) {
        if (w.startsWith("of=")) writes.push({ path: unquote(w.slice(3)), kind: "dd" });
      }
    }
  }

  // De-duplicate by path, keeping the first kind seen.
  const seen = new Set<string>();
  return writes.filter((w) => {
    if (!w.path || seen.has(w.path)) return false;
    seen.add(w.path);
    return true;
  });
}

/** True when the command writes to the filesystem through the shell. */
export function hasWriteRedirection(cmd: string): boolean {
  return detectWriteTargets(cmd).length > 0;
}

function unquote(word: string): string {
  if (word.length >= 2 && (word[0] === '"' || word[0] === "'") && word[word.length - 1] === word[0]) {
    return word.slice(1, -1);
  }
  return word.replace(/\\(.)/g, "$1");
}

/** The first whitespace-delimited word of `s`, honoring quotes. */
function firstWord(s: string): string {
  return splitWords(s)[0] ?? "";
}

/** Split on unquoted whitespace, keeping quoted runs together. */
function splitWords(s: string): string[] {
  const words: string[] = [];
  let cur = "";
  let quote: '"' | "'" | null = null;
  for (let i = 0; i < s.length; i++) {
    const ch = s[i];
    if (quote === null && ch === "\\") {
      cur += ch + (s[i + 1] ?? "");
      i++;
      continue;
    }
    if (quote === null && (ch === '"' || ch === "'")) {
      quote = ch;
      cur += ch;
      continue;
    }
    if (quote !== null && ch === quote) {
      quote = null;
      cur += ch;
      continue;
    }
    if (quote === null && /\s/.test(ch)) {
      if (cur) words.push(cur);
      cur = "";
      continue;
    }
    // An unquoted redirect ends the current word (`cat>f` is two words).
    if (quote === null && (ch === ">" || ch === "<")) {
      if (cur) words.push(cur);
      cur = "";
      continue;
    }
    cur += ch;
  }
  if (cur) words.push(cur);
  return words;
}
