// Local prompt-size estimation, for providers whose reported input token count
// cannot be trusted to detect overflow.
//
// Issue #128 (@brlucasdx), measured rather than inferred: Ollama reports
// `prompt_eval_count` AFTER truncation. Sent ~50k tokens of Python at a
// `num_ctx` of 32768, it answered with `prompt_eval_count: 16386`: half the
// window, plus two. No error, and no indication anywhere in the response that
// the older half of the prompt had been dropped. A distinctive constant placed
// at 50% depth came back "not found".
//
// That breaks the watchdog in a specific way. `overflow.js` already handles
// silent overflow for other providers by testing `usage.input > contextWindow`,
// and under Ollama the reported input can never exceed ~half the window, so
// that test can never fire. The reported figure the threshold reads climbs to
// its ceiling and stops. brlucasdx watched the status bar reach `110.0% / 33k`
// before compaction ran, by which point the runtime had been silently dropping
// the older half of the conversation on every request, the visible symptom
// being the agent re-deriving the same diagnosis and re-reading files it had
// already read.
//
// The fix is to stop relying on the provider for the one number it is known to
// get wrong, and measure the conversation ourselves.

import type { ContextUsageLike } from "./index.ts";

/** Characters per token. English prose runs ~4; code runs nearer 3, so 4 is a
 *  deliberate UNDER-estimate of a code-heavy transcript. That direction matters:
 *  the estimate is only ever used to compact EARLIER than the provider's
 *  reading would, so erring low means erring toward the existing behaviour. */
export const CHARS_PER_TOKEN = 4;

/** Providers whose reported input token count is measured post-truncation and
 *  therefore cannot be used to detect overflow.
 *
 *  Deliberately a list of one. Every other provider we ship reports the whole
 *  prompt, and substituting a local estimate for a correct reading would only
 *  add error. This is not a general "don't trust usage" switch; it is a named
 *  workaround for a named, measured defect. */
const UNTRUSTED_INPUT_REPORTERS = new Set(["ollama"]);

export function reportsPostTruncationInput(
  provider: string | undefined,
  env: NodeJS.ProcessEnv = process.env,
): boolean {
  const forced = (env.LITTLE_CODER_LOCAL_CONTEXT_ESTIMATE ?? "").trim().toLowerCase();
  if (forced === "1" || forced === "always") return true;
  if (forced === "0" || forced === "off" || forced === "never") return false;
  return provider !== undefined && UNTRUSTED_INPUT_REPORTERS.has(provider.toLowerCase());
}

/** Total characters in whatever pi would actually send. Walks the value
 *  generically instead of matching pi's entry shapes: the shapes change
 *  between pi releases, and an estimate that silently returns 0 after an
 *  upgrade is worse than a slightly loose one. */
export function charLength(value: unknown, depth = 0): number {
  if (depth > 12 || value == null) return 0;
  if (typeof value === "string") return value.length;
  if (typeof value === "number" || typeof value === "boolean") return String(value).length;
  if (Array.isArray(value)) {
    let n = 0;
    for (const v of value) n += charLength(v, depth + 1);
    return n;
  }
  if (typeof value === "object") {
    let n = 0;
    for (const v of Object.values(value as Record<string, unknown>)) n += charLength(v, depth + 1);
    return n;
  }
  return 0;
}

/** Estimated prompt tokens from the compaction-aware entry list plus the system
 *  prompt. `buildContextEntries()` is pi's own answer to "what is in context
 *  right now", so this counts what the provider is being sent, not the whole
 *  session file. */
export function estimateContextTokens(entries: unknown, systemPrompt: string | undefined): number {
  const chars = charLength(entries) + (systemPrompt?.length ?? 0);
  return Math.ceil(chars / CHARS_PER_TOKEN);
}

/**
 * Reconcile a provider's reported usage with a local estimate.
 *
 * `max` rather than "prefer the estimate": the estimate omits tool schemas and
 * per-message framing, so it is a lower bound on the real prompt. Taking the
 * larger of the two can only ever move compaction EARLIER than the reported
 * figure would, never later, which is the safe direction for a guard whose
 * failure mode is arriving too late.
 *
 * Returns the usage unchanged when there is nothing to reconcile: no reading
 * yet, no window, or a provider that reports honestly.
 */
export function reconcileUsage(
  usage: ContextUsageLike | undefined,
  estimatedTokens: number,
  untrusted: boolean,
): ContextUsageLike | undefined {
  if (!usage || !untrusted) return usage;
  if (usage.contextWindow <= 0) return usage;
  const reported = usage.tokens ?? 0;
  if (estimatedTokens <= reported) return usage;
  return {
    tokens: estimatedTokens,
    contextWindow: usage.contextWindow,
    percent: (estimatedTokens / usage.contextWindow) * 100,
  };
}

/** Whether the gap between the two readings is wide enough to be worth telling
 *  the user about once. A small gap is ordinary estimation error; a reading
 *  pinned near half the window while the transcript is far larger is the
 *  truncation signature from the issue, and the user should know their model
 *  has been quietly losing the middle of the conversation. */
export function looksTruncated(reportedTokens: number | null, estimatedTokens: number): boolean {
  if (reportedTokens === null || reportedTokens <= 0) return false;
  return estimatedTokens > reportedTokens * 1.5;
}
