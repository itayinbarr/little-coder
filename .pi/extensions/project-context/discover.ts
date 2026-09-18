// Pure discovery + shaping for the project-context extension, kept separate
// from the pi wiring in index.ts so it can be unit-tested without a runtime.
//
// Issue #104 (@highlyunavailable, confirmed by @dcazrael): little-coder
// launches pi with `--no-context-files` so that ITS AGENTS.md is the system
// prompt rather than whatever the cwd happens to hold. That was a deliberate
// choice and it is still the right default for the file's *role*, but it also
// meant a project's own AGENTS.md was ignored outright, and there was no way
// left to inject per-project information. The reported symptom is the cost:
// "my Qwen 3.6 35B keeps doing a massive glob at the start of every run to see
// what the environment looks like", which is precisely the scan a project
// AGENTS.md exists to prevent.
//
// So the project file is loaded, and it is loaded as an ADDITION rather than a
// replacement: little-coder's own system prompt still governs how the model
// behaves, and the project file tells it about this repository.

import { existsSync, readFileSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";

/** Filenames searched, in order, at each directory level. AGENTS.md is the
 *  agreed cross-agent convention and the one both reporters named; CLAUDE.md is
 *  accepted because a great many repositories have only that one, and a user
 *  who has written project instructions does not care which agent named the
 *  file. The FIRST hit at a level wins: a repo carrying both is not two sets
 *  of instructions, it is the same instructions twice. */
export const CONTEXT_FILENAMES = ["AGENTS.md", "CLAUDE.md"] as const;

/** Default cap on injected characters. little-coder's whole premise is a small
 *  cold-start context (~7k tokens), and an unbounded project file would eat it
 *  silently. @CrazyAce25 raised exactly this concern about static injection in
 *  #126. 4000 characters is roughly 1k tokens: enough for the "here is what
 *  this repo is and where the rules live" preamble these files are used for,
 *  and small enough that a model with a 32k window is not measurably poorer for
 *  it. Truncation is reported rather than silent, both to the user and to the
 *  model, so nobody debugs a rule that was cut off without knowing. */
export const DEFAULT_MAX_CHARS = 4000;

export interface FoundContext {
  path: string;
  content: string;
  /** Characters dropped by the cap, 0 when the file fit. */
  truncatedChars: number;
}

/**
 * Walk up from `startDir` looking for the nearest context file.
 *
 * Upward rather than cwd-only because running the agent from a subdirectory of
 * a repository is normal and the repository's instructions still apply there.
 * `skipPaths` holds files that must never be loaded, in practice
 * little-coder's own AGENTS.md, which is ALREADY the system prompt: launching
 * little-coder inside its own checkout would otherwise inject a second copy of
 * the thing it is running on.
 */
export function findContextFile(
  startDir: string,
  skipPaths: readonly string[] = [],
  exists: (p: string) => boolean = existsSync,
): string | undefined {
  const skip = new Set(skipPaths.map((p) => resolve(p)));
  let dir = resolve(startDir);
  for (;;) {
    for (const name of CONTEXT_FILENAMES) {
      const candidate = join(dir, name);
      if (exists(candidate) && !skip.has(resolve(candidate))) return candidate;
    }
    const parent = dirname(dir);
    if (parent === dir) return undefined;
    dir = parent;
  }
}

/** Apply the character cap, reporting how much was dropped. Cuts at the last
 *  newline inside the budget when there is one, so the model is never handed
 *  half a sentence to interpret as a complete rule. */
export function capContent(content: string, maxChars: number): { content: string; truncatedChars: number } {
  if (maxChars <= 0 || content.length <= maxChars) return { content, truncatedChars: 0 };
  const head = content.slice(0, maxChars);
  const lastBreak = head.lastIndexOf("\n");
  const kept = lastBreak > maxChars / 2 ? head.slice(0, lastBreak) : head;
  return { content: kept, truncatedChars: content.length - kept.length };
}

/** Read and shape the nearest context file. Returns undefined when there is
 *  none, when it is empty, or when anything at all goes wrong: a project file
 *  that cannot be read is not worth failing a launch over. */
export function loadProjectContext(
  startDir: string,
  opts: { skipPaths?: readonly string[]; maxChars?: number } = {},
): FoundContext | undefined {
  const path = findContextFile(startDir, opts.skipPaths ?? []);
  if (!path) return undefined;
  try {
    // A directory named AGENTS.md, or a file too large to be instructions,
    // should not be read into the prompt at all.
    if (!statSync(path).isFile()) return undefined;
    const raw = readFileSync(path, "utf-8").trim();
    if (!raw) return undefined;
    const { content, truncatedChars } = capContent(raw, opts.maxChars ?? DEFAULT_MAX_CHARS);
    return { path, content, truncatedChars };
  } catch {
    return undefined;
  }
}

/**
 * The block appended to the system prompt.
 *
 * Two deliberate choices about the wording, both aimed at small models:
 *
 * 1. It says what the block IS and where it came from. A model handed
 *    unattributed text at the end of its system prompt has been seen to treat
 *    it as the user's first message and answer it.
 * 2. It names little-coder's own instructions as the ones that win on conflict.
 *    Project files routinely say things like "always run the full test suite",
 *    and a small model resolving that against a harness rule is the failure
 *    mode #94 is a monument to. The precedence is stated rather than left to be
 *    inferred.
 */
export function formatProjectContext(found: FoundContext): string {
  const note =
    found.truncatedChars > 0
      ? `\n\n[truncated: ${found.truncatedChars} more characters in this file were not included. ` +
        `Read ${found.path} directly if you need the rest.]`
      : "";
  return (
    `\n\n<project_instructions source="${found.path}">\n` +
    `These are the instructions for THIS project, read from the file above. ` +
    `They describe the repository you are working in: its conventions, its layout, and where its rules live. ` +
    `Follow them. Where they conflict with your operating instructions above, your operating instructions win.\n\n` +
    found.content +
    note +
    `\n</project_instructions>\n`
  );
}

/** `LITTLE_CODER_PROJECT_CONTEXT=0` (or `off`/`false`) turns the whole thing
 *  off, for anyone who chose `--no-context-files` behaviour on purpose. */
export function isEnabled(env: NodeJS.ProcessEnv = process.env): boolean {
  const v = env.LITTLE_CODER_PROJECT_CONTEXT;
  return !(v === "0" || v === "off" || v === "false");
}

/** `LITTLE_CODER_PROJECT_CONTEXT_MAX_CHARS` overrides the cap; 0 means "no cap"
 *  for someone who has decided their context budget is their own business. */
export function maxChars(env: NodeJS.ProcessEnv = process.env): number {
  const raw = Number(env.LITTLE_CODER_PROJECT_CONTEXT_MAX_CHARS);
  if (!Number.isFinite(raw) || raw < 0) return DEFAULT_MAX_CHARS;
  return raw === 0 ? Number.MAX_SAFE_INTEGER : raw;
}
