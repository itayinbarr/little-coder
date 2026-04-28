import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";

// Port of the thinking-budget cap + partial-trace reuse logic from
// providers.py. little-coder's Python implementation aborts the stream
// mid-flight when thinking tokens cross the budget, re-injects the partial
// trace as assistant context, and retries with thinking disabled. Pi's
// AgentSession doesn't expose mid-stream abort-and-replace, so we implement
// the between-turn fallback documented in the plan:
//
//  1. Count thinking_delta tokens during message_update
//  2. On budget exceed, call ctx.abort() to end the turn
//  3. On turn_end after abort, flip thinking level to "off" and queue a
//     correction follow-up nudging the model to commit to an implementation
//
// The behavioral effect matches the whitepaper's claim that the budget cap
// "forces the model out of open-ended deliberation and back into committing
// to an implementation" — the concrete savings of preserving the partial
// trace are lost, but the commit-to-action pressure is the same.
//
// Idempotency notes (issue #8 fix):
//   - State is reset on `agent_start` AND `turn_start` so a previous run
//     leaving `aborted=true` cannot leak into the next conversation.
//   - `recoveryPending` gates re-entry: while a recovery is mid-flight,
//     message_update / turn_start cannot re-arm the abort.
//   - The recovery sequence yields one tick (setImmediate) so pi's async
//     abort barrier settles before we queue the follow-up message; without
//     this, fast-streaming local backends drop the follow-up silently and
//     the agent appears to stop.

const DEFAULT_BUDGET = 2048;

// Per-run rolling state (reset on agent_start)
let thinkingChars = 0;
let budgetForTurn = DEFAULT_BUDGET;
let aborted = false;
let recoveryPending = false;

function charsToTokens(chars: number): number {
  // Matches local/context_manager.estimate_tokens (len/3.5)
  return Math.ceil(chars / 3.5);
}

export default function (pi: ExtensionAPI) {
  // Hard reset between conversations. agent_start fires once per /run; if a
  // previous run aborted, `aborted` and `recoveryPending` would otherwise
  // leak into the next conversation.
  pi.on("agent_start", async () => {
    thinkingChars = 0;
    aborted = false;
    recoveryPending = false;
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
    // Don't clear `aborted` if a recovery is mid-flight — the recovery
    // turn_end handler clears it once the follow-up has been queued.
    if (!recoveryPending) aborted = false;
  });

  pi.on("message_update", async (event, ctx) => {
    const ev: any = (event as any).assistantMessageEvent;
    if (!ev) return;
    if (ev.type !== "thinking_delta") return;
    const delta = typeof ev.delta === "string" ? ev.delta : "";
    thinkingChars += delta.length;
    if (aborted || recoveryPending) return;
    const tokens = charsToTokens(thinkingChars);
    if (tokens > budgetForTurn) {
      aborted = true;
      recoveryPending = true;
      ctx.ui.notify(
        `thinking-budget: ${tokens} > ${budgetForTurn} — aborting turn, will retry with thinking off`,
        "warning",
      );
      ctx.abort();
    }
  });

  pi.on("turn_end", async (_event, _ctx) => {
    if (!recoveryPending) return;
    // Yield one tick so pi's abort barrier settles before we queue the
    // follow-up. On fast-streaming local backends (qwen3.6 / llama.cpp)
    // queuing immediately after ctx.abort() drops the follow-up silently
    // and the agent appears to stop with no message — issue #8.
    await new Promise<void>((r) => setImmediate(r));
    pi.setThinkingLevel("off");
    pi.sendUserMessage(
      "[thinking budget exceeded] Please commit to an implementation now. Stop deliberating and use your tools to make progress.",
      { deliverAs: "followUp" },
    );
    recoveryPending = false;
    aborted = false;
  });
}
