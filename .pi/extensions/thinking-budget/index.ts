import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { harnessIntervention } from "../_shared/intervention.ts";

// pi's thinking-level union (not re-exported from the package root). Mirrors
// settings-manager's ThinkingLevel; structurally assignable to pi's own type.
type ThinkingLevel = "off" | "minimal" | "low" | "medium" | "high" | "xhigh" | "max";

// Port of the thinking-budget cap + partial-trace reuse logic from
// providers.py. little-coder's Python implementation aborts the stream
// mid-flight when thinking tokens cross the budget, re-injects the partial
// trace as assistant context, and retries with thinking disabled. Pi's
// AgentSession doesn't expose mid-stream abort-and-replace, so we approximate
// it: count thinking tokens, and on breach disable thinking + queue a
// commit-to-an-implementation nudge, then abort the over-long turn.
//
// ── Issue #8, second reproduction (1.4.3) ───────────────────────────────────
// The v1.0.0 fix deferred the recovery (`setThinkingLevel("off")` +
// `sendUserMessage`) to a `turn_end` handler, after a `setImmediate` yield, and
// ran it against the module-scope `pi`. But `ctx.abort()` makes pi's `agent_end`
// run auto-retry / auto-compaction (both enabled in .pi/settings.json), which
// REPLACES the session (dispose() → ExtensionRunner.invalidate()). The
// setImmediate yield is exactly what let that replacement land *before* the
// deferred recovery, so the recovery touched a now-stale `pi` and threw
// ("This extension ctx is stale after session replacement or reload"). Net
// effect: thinking was never turned off (the next step kept thinking) and the
// follow-up never reached the model (the agent appeared to stop) — the #8
// symptom, on a different mechanism than the original.
//
// Fix: do the whole recovery SYNCHRONOUSLY inside `message_update`, BEFORE
// `ctx.abort()`, while `pi` is still live and the session hasn't been replaced.
// No `turn_end` handler, no `setImmediate` — nothing runs against a stale ref.
//
//   1. Count thinking_delta tokens during message_update.
//   2. On breach: capture the current thinking level, flip thinking to "off",
//      queue the commit nudge as a follow-up, surface one harness-intervention
//      line, THEN ctx.abort().
//   3. Keep thinking off across the restart turn(s): `forcedOff` re-asserts
//      "off" on every turn_start until the user submits a genuinely new prompt
//      (`input` event), at which point the prior level is restored so the next
//      task can think again. (A new task should not inherit "off" just because
//      a previous one over-thought.)

const DEFAULT_BUDGET = 4096;

// Per-run rolling state.
let thinkingChars = 0;
let budgetForTurn = DEFAULT_BUDGET;
let aborted = false;
// True from a budget breach until the next genuine user input. While set, we
// re-assert thinking "off" at the start of every turn so the restart turn (and
// any follow-on turns of the same task) can't silently come back with thinking
// re-enabled by the post-replacement profile resolution.
let forcedOff = false;
// The thinking level in effect when we first forced it off, restored on the
// next user input so a new task is unaffected.
let priorLevel: ThinkingLevel | undefined;

function charsToTokens(chars: number): number {
  // Matches local/context_manager.estimate_tokens (len/3.5)
  return Math.ceil(chars / 3.5);
}

// setThinkingLevel / getThinkingLevel are guarded: a stale-ctx throw must never
// escape (pi reports an uncaught extension throw as a hard "Extension error"),
// and older SDK builds may lack the getter.
function safeGetThinkingLevel(pi: ExtensionAPI): ThinkingLevel | undefined {
  try {
    return typeof pi.getThinkingLevel === "function" ? pi.getThinkingLevel() : undefined;
  } catch {
    return undefined;
  }
}

function safeSetThinkingLevel(pi: ExtensionAPI, level: ThinkingLevel): void {
  try {
    pi.setThinkingLevel(level);
  } catch {
    // Stale ctx / unsupported — leave the level alone rather than crash the run.
  }
}

export default function (pi: ExtensionAPI) {
  // A new session (startup, /clear, resume, reload) is a clean slate — clear
  // everything, including the forced-off window. The recovery restart does NOT
  // fire session_start (it's a follow-up within the same session), so this
  // never clobbers the re-assertion. Also stops module-scoped state leaking
  // across sessions in-process.
  pi.on("session_start", async () => {
    thinkingChars = 0;
    aborted = false;
    forcedOff = false;
    priorLevel = undefined;
  });

  // Hard reset of per-turn counters between agent runs. `forcedOff` /
  // `priorLevel` are deliberately NOT reset here: agent_start ALSO fires for
  // the recovery restart turn, and clearing the force there would let thinking
  // come straight back on — exactly the bug. They are cleared on `input`
  // (a genuinely new user task) or `session_start`.
  pi.on("agent_start", async () => {
    thinkingChars = 0;
    aborted = false;
  });

  // A genuinely new user prompt ends the "forced off" window: restore the
  // level the user actually had before the breach. Programmatic follow-ups
  // (our nudge) do not emit an `input` event, so the restart turn stays off.
  pi.on("input", async () => {
    if (forcedOff) {
      if (priorLevel !== undefined) safeSetThinkingLevel(pi, priorLevel);
      forcedOff = false;
      priorLevel = undefined;
    }
    thinkingChars = 0;
    aborted = false;
  });

  pi.on("before_agent_start", async (event) => {
    const opts: any = (event as any).systemPromptOptions ?? {};
    const lc = opts.littleCoder ?? {};
    const profileBudget = Number(lc.thinkingBudget);
    const envBudget = Number(process.env.LITTLE_CODER_THINKING_BUDGET);
    budgetForTurn =
      (Number.isFinite(profileBudget) && profileBudget > 0 && profileBudget) ||
      (Number.isFinite(envBudget) && envBudget > 0 && envBudget) ||
      DEFAULT_BUDGET;
  });

  pi.on("turn_start", async () => {
    thinkingChars = 0;
    aborted = false;
    // Re-assert "off" for the restart turn (and any follow-on turns of the same
    // task). After the session replacement triggered by the abort, the new
    // run can otherwise resolve thinking back to the profile default.
    if (forcedOff) safeSetThinkingLevel(pi, "off");
  });

  pi.on("message_update", async (event, ctx) => {
    const ev: any = (event as any).assistantMessageEvent;
    if (!ev) return;
    if (ev.type !== "thinking_delta") return;
    const delta = typeof ev.delta === "string" ? ev.delta : "";
    thinkingChars += delta.length;
    if (aborted) return;
    const tokens = charsToTokens(thinkingChars);
    if (tokens <= budgetForTurn) return;

    // Breach. Do the entire recovery now, while `pi` is still live — BEFORE
    // ctx.abort() triggers the session replacement that would make `pi` stale.
    aborted = true;
    if (!forcedOff) {
      priorLevel = safeGetThinkingLevel(pi);
      forcedOff = true;
    }
    safeSetThinkingLevel(pi, "off");
    try {
      pi.sendUserMessage(
        "[thinking budget exceeded] Please commit to an implementation now. " +
          "Stop deliberating and use your tools to make progress.",
        { deliverAs: "followUp" },
      );
    } catch {
      // SDK without sendUserMessage — abort still forces the turn to end.
    }
    harnessIntervention(
      ctx,
      "the model has thought long enough — forcing it to start implementing.",
    );
    ctx.abort();
  });
}
