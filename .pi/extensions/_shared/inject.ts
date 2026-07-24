// Where little-coder's per-turn context augmentation lands (issue #73).
//
// Four extensions add a block of guidance to a turn: skill-inject (tool skill
// cards + the research directive), knowledge-inject (algorithm reference
// entries), plan-mode (planning instructions + research), and deep-research
// (the report brief). All four used to append to the SYSTEM PROMPT.
//
// That destroyed the KV cache. The system prompt is the first thing in the
// request, so changing it invalidates the entire cached prefix — and these
// blocks are recomputed per turn from the user's prompt, so they changed
// almost every turn. manueloverride caught it with `cache-hunter`: llama.cpp
// re-churning 120k of message history "for no reason" mid-conversation.
//
// pi already has the right hook. `before_agent_start` may return a `message`
// instead of a `systemPrompt` (core/extensions/types.d.ts::
// BeforeAgentStartEventResult); pi appends it AFTER the user's message
// (core/agent-session.js) and converts `role: "custom"` to a `user` message on
// the way to the provider (core/messages.js::convertToLlm). So the block lands
// at the TAIL of the conversation with every preceding byte untouched — the
// prefix stays cached and only the new tokens are processed.
//
// The recency argument that put these blocks last in the system prompt gets
// stronger, not weaker: small models weight the end of the context most, and
// the conversation tail is as late as it gets.
//
// `LITTLE_CODER_INJECT_MODE=system` restores the old system-prompt behavior,
// which is what the whitepaper scaffold reproduction was measured against.

export type InjectMode = "message" | "system";

/** Shape of what a `before_agent_start` handler may return. */
export interface InjectionResult {
  systemPrompt?: string;
  message?: {
    customType: string;
    content: string;
    /** false → carried in context but not rendered in the transcript. */
    display: boolean;
  };
}

export function injectMode(env: NodeJS.ProcessEnv = process.env): InjectMode {
  return env.LITTLE_CODER_INJECT_MODE === "system" ? "system" : "message";
}

/**
 * Build the `before_agent_start` return value for a block of injected guidance.
 *
 * @param customType  Stable id for this injector (`lc-skills`, `lc-knowledge`,
 *                    …) so the blocks are distinguishable in the session log.
 * @param block       The text to inject. Returns undefined when empty.
 * @param systemPrompt The turn's system prompt — only read in `system` mode.
 */
export function injectionResult(
  customType: string,
  block: string,
  systemPrompt = "",
  env: NodeJS.ProcessEnv = process.env,
): InjectionResult | undefined {
  if (!block) return undefined;
  if (injectMode(env) === "system") {
    return { systemPrompt: systemPrompt + block };
  }
  return { message: { customType, content: block, display: false } };
}

/**
 * Suppress a block that is byte-identical to the one this injector added last.
 *
 * A tail message persists in the conversation, unlike a system prompt that is
 * rebuilt each turn — so re-sending the same skill cards every turn would pile
 * up duplicate copies and spend context for nothing. The previous copy is
 * still there and still visible to the model, so skipping is free.
 *
 * Returns a `shouldInject` predicate that remembers the last block it accepted.
 * In `system` mode it always returns true: there the block is rebuilt from
 * scratch each turn and skipping it would drop the guidance entirely.
 */
export function makeDedupe(env: NodeJS.ProcessEnv = process.env): (block: string) => boolean {
  let last: string | null = null;
  return (block: string): boolean => {
    if (injectMode(env) === "system") return true;
    if (block === last) return false;
    last = block;
    return true;
  };
}
