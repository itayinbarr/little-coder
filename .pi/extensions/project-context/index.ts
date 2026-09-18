import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { createHash } from "node:crypto";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { injectionResult, makeDedupe } from "../_shared/inject.ts";
import {
  formatProjectContext,
  isEnabled,
  loadProjectContext,
  maxChars,
  type FoundContext,
} from "./discover.ts";

// Issue #104: load the project's own AGENTS.md (or CLAUDE.md) and append it to
// the system prompt.
//
// The launcher passes pi `--no-context-files` so that little-coder's AGENTS.md
// is the system prompt rather than whatever the cwd holds. That is still right
// for the *harness* instructions (the small-model adaptations are the product)
// but it also threw away the project's own file, which is a different thing
// serving a different purpose. @highlyunavailable's report is the cost stated
// plainly: with nothing to tell it what the repository is, the model globs the
// whole tree at the start of every run. @dcazrael's is sharper still: his
// AGENTS.md exists to say "RULES.md is mandatory, LLM.txt is the map", i.e. to
// CONTROL discovery, so the file arriving only if the model happens to find it
// defeats the entire point.
//
// Three properties keep this from undoing the reason `--no-context-files` is
// there in the first place:
//
//   * It ADDS. little-coder's own prompt still governs behaviour, and the
//     injected block says so explicitly, so a project file cannot quietly
//     re-specify the harness.
//   * It is CAPPED (see DEFAULT_MAX_CHARS), and truncation is reported rather
//     than silent. The ~7k cold-start budget is the product; an unbounded
//     project file would eat it invisibly.
//   * It NEVER loads little-coder's own AGENTS.md, which is already the system
//     prompt. Otherwise running little-coder on itself injects a second copy.

const here = dirname(fileURLToPath(import.meta.url));
const ownAgentsMd = resolve(join(here, "..", "..", "..", "AGENTS.md"));

function shortHash(s: string): string {
  return createHash("sha256").update(s).digest("hex").slice(0, 12);
}

export default function (pi: ExtensionAPI) {
  if (!isEnabled()) return; // registers nothing, costs nothing

  // Resolved once at startup, not per turn: the cwd does not move under a
  // session, and re-reading the file every turn would make a mid-session edit
  // to AGENTS.md change the prompt underneath a conversation that has already
  // acted on the old one.
  let found: FoundContext | undefined;
  try {
    found = loadProjectContext(process.cwd(), {
      skipPaths: [ownAgentsMd],
      maxChars: maxChars(),
    });
  } catch {
    found = undefined; // never block a launch over this
  }

  pi.registerCommand("project-context", {
    description: "Show the project AGENTS.md / CLAUDE.md loaded into this session",
    handler: async (_args: string, ctx: any) => {
      if (!found) {
        ctx.ui?.notify?.(
          `no project AGENTS.md or CLAUDE.md found from ${process.cwd()} upward`,
          "warning",
        );
        return;
      }
      const truncated =
        found.truncatedChars > 0 ? `, ${found.truncatedChars} chars truncated` : "";
      ctx.ui?.notify?.(
        `project context: ${found.path} (${found.content.length} chars${truncated}, sha256:${shortHash(found.content)})`,
        "info",
      );
    },
  });

  if (!found) return;

  // Injected as a hidden TAIL message, not appended to the system prompt
  // (issue #73). A system-prompt append would invalidate the cached prefix for
  // the whole conversation, which on a local model means llama.cpp reprocessing
  // the entire history. The block is identical every turn, so the dedupe sends
  // it exactly once and every later turn is free: the copy is still in the
  // conversation and still visible to the model.
  const shouldInject = makeDedupe();
  const block = formatProjectContext(found);

  pi.on("before_agent_start", async (event) => {
    if (!shouldInject(block)) return;
    return injectionResult("lc-project-context", block, (event as any).systemPrompt);
  });
}
