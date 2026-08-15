// The set of tools the current process may actually call.
//
// tool-gating enforces LITTLE_CODER_ALLOWED_TOOLS at `tool_call` time, and
// subagent/spawn.ts sets it for every sub-coder child (SUBCODER_ALLOWED_TOOLS:
// read + search + browse, no edit/write, no dispatch). The injection
// extensions need the same view *before* the turn starts, so they never hand
// the model guidance that names a tool the gate will refuse.
//
// Issue #97: a research sub-coder was being injected with the evidence-first
// research protocol — "call EvidenceList before answering; if it is empty you
// are not ready to answer" — while EvidenceAdd/EvidenceList were not in its
// allow-list. The child could not satisfy step 4 by construction, so it either
// looped or reported that it had no evidence. knowledge-inject had a
// `lc.isSubtask` guard meant to prevent exactly this, but nothing in
// little-coder or pi has ever set that flag, so it never fired.
//
// Returns undefined when no allow-list is configured, which means "every tool
// is available" — the normal case for a top-level session.

export function allowedToolSet(littleCoderOpts?: {
  allowedTools?: unknown;
}): Set<string> | undefined {
  let list: string[] | undefined = Array.isArray(littleCoderOpts?.allowedTools)
    ? (littleCoderOpts.allowedTools as string[])
    : undefined;

  // Fall back to the env var directly. pi runs before_agent_start handlers in
  // extension load order (alphabetical), so knowledge-inject and skill-inject
  // both fire before tool-gating publishes the list onto systemPromptOptions.
  if (!list && process.env.LITTLE_CODER_ALLOWED_TOOLS) {
    list = process.env.LITTLE_CODER_ALLOWED_TOOLS
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
  }

  return list && list.length > 0 ? new Set(list) : undefined;
}

/** True when every tool in `required` is callable (or nothing is gated). */
export function toolsAvailable(
  required: readonly string[],
  allowed: Set<string> | undefined,
): boolean {
  if (!allowed) return true;
  return required.every((t) => allowed.has(t));
}
