import { describe, it, expect, beforeEach } from "vitest";
import setupExtension from "./index.ts";

// Exercise the char→token conversion (matches local/context_manager.py)
function charsToTokens(chars: number): number {
  return Math.ceil(chars / 3.5);
}

describe("thinking budget token estimation", () => {
  it("converts chars to tokens via /3.5", () => {
    expect(charsToTokens(0)).toBe(0);
    expect(charsToTokens(3)).toBe(1);
    expect(charsToTokens(7)).toBe(2);
    expect(charsToTokens(3500)).toBe(1000);
  });
  it("2048 tokens ~ 7168 chars", () => {
    // Budget trigger boundary: ceil(7169/3.5) = 2049 > 2048
    expect(charsToTokens(7168)).toBe(2048);
    expect(charsToTokens(7169)).toBeGreaterThan(2048);
  });
});

// ── Issue #8 regression coverage ────────────────────────────────────────
// Mock just enough of pi's ExtensionAPI for the handler choreography.
// We capture every registered handler keyed by event name and drive them
// directly to assert idempotency / sequencing.

interface Handler {
  (event: any, ctx: any): Promise<unknown> | unknown;
}

interface MockPi {
  on: (name: string, h: Handler) => void;
  handlers: Record<string, Handler[]>;
  followUps: string[];
  thinkingLevels: string[];
  setThinkingLevel: (lvl: string) => void;
  sendUserMessage: (msg: string, opts?: any) => void;
}

function makePi(): MockPi {
  const handlers: Record<string, Handler[]> = {};
  return {
    handlers,
    followUps: [],
    thinkingLevels: [],
    on(name, h) {
      (handlers[name] ??= []).push(h);
    },
    setThinkingLevel(lvl) {
      this.thinkingLevels.push(lvl);
    },
    sendUserMessage(msg, _opts) {
      this.followUps.push(msg);
    },
  } as MockPi;
}

function makeCtx() {
  const aborts: number[] = [];
  return {
    aborts,
    abort: () => { aborts.push(1); },
    ui: { notify: (_m: string, _l?: string) => {} },
  };
}

async function fire(pi: MockPi, name: string, event: any, ctx: any) {
  for (const h of pi.handlers[name] ?? []) {
    await h(event, ctx);
  }
}

function thinkingDelta(s: string) {
  return { assistantMessageEvent: { type: "thinking_delta", delta: s } };
}

describe("thinking-budget idempotency (issue #8)", () => {
  beforeEach(() => {
    // Force a small budget so we can trigger with short strings.
    process.env.LITTLE_CODER_THINKING_BUDGET = "10";
  });

  it("fires exactly one abort + one follow-up for a single budget breach across many bursts", async () => {
    const pi = makePi();
    const ctx = makeCtx();
    setupExtension(pi as any);
    await fire(pi, "agent_start", {}, ctx);
    await fire(pi, "before_agent_start", { systemPromptOptions: {} }, ctx);
    await fire(pi, "turn_start", {}, ctx);

    // Burst: 1000 chars of thinking, way over 10-token budget.
    await fire(pi, "message_update", thinkingDelta("x".repeat(1000)), ctx);
    // Second burst on the same turn — must not double-abort.
    await fire(pi, "message_update", thinkingDelta("y".repeat(1000)), ctx);
    // Third burst.
    await fire(pi, "message_update", thinkingDelta("z".repeat(1000)), ctx);

    await fire(pi, "turn_end", {}, ctx);

    expect(ctx.aborts.length).toBe(1);
    expect(pi.followUps.length).toBe(1);
    expect(pi.followUps[0]).toMatch(/thinking budget exceeded/i);
    expect(pi.thinkingLevels).toEqual(["off"]);
  });

  it("fires the recovery follow-up only once even if turn_end is re-emitted", async () => {
    const pi = makePi();
    const ctx = makeCtx();
    setupExtension(pi as any);
    await fire(pi, "agent_start", {}, ctx);
    await fire(pi, "before_agent_start", { systemPromptOptions: {} }, ctx);
    await fire(pi, "turn_start", {}, ctx);
    await fire(pi, "message_update", thinkingDelta("x".repeat(1000)), ctx);
    await fire(pi, "turn_end", {}, ctx);
    // Pi can re-emit turn_end during retry / compaction paths — must be a no-op.
    await fire(pi, "turn_end", {}, ctx);
    await fire(pi, "turn_end", {}, ctx);

    expect(ctx.aborts.length).toBe(1);
    expect(pi.followUps.length).toBe(1);
    expect(pi.thinkingLevels.length).toBe(1);
  });

  it("resets state on agent_start so a prior aborted run does not leak", async () => {
    const pi = makePi();
    const ctx1 = makeCtx();
    setupExtension(pi as any);

    // Run 1: trigger an abort.
    await fire(pi, "agent_start", {}, ctx1);
    await fire(pi, "before_agent_start", { systemPromptOptions: {} }, ctx1);
    await fire(pi, "turn_start", {}, ctx1);
    await fire(pi, "message_update", thinkingDelta("x".repeat(1000)), ctx1);
    await fire(pi, "turn_end", {}, ctx1);

    // Run 2: fresh agent_start — no abort should fire on the first turn
    // even though run 1 left state behind.
    const ctx2 = makeCtx();
    await fire(pi, "agent_start", {}, ctx2);
    await fire(pi, "before_agent_start", { systemPromptOptions: {} }, ctx2);
    await fire(pi, "turn_start", {}, ctx2);
    // A small thinking delta well under budget.
    await fire(pi, "message_update", thinkingDelta("ok"), ctx2);
    await fire(pi, "turn_end", {}, ctx2);

    expect(ctx2.aborts.length).toBe(0);
    // Total follow-ups: only the one from run 1.
    expect(pi.followUps.length).toBe(1);
  });

  it("yields one tick before sendUserMessage so pi's abort barrier can settle", async () => {
    // We can only assert this indirectly: turn_end must complete the await
    // chain (it returns a Promise) AFTER setImmediate fires. If it didn't
    // yield, sendUserMessage would land synchronously inside the same
    // microtask as ctx.abort(). Verify ordering by interleaving a marker.
    const pi = makePi();
    const ctx = makeCtx();
    setupExtension(pi as any);
    await fire(pi, "agent_start", {}, ctx);
    await fire(pi, "before_agent_start", { systemPromptOptions: {} }, ctx);
    await fire(pi, "turn_start", {}, ctx);
    await fire(pi, "message_update", thinkingDelta("x".repeat(1000)), ctx);

    const order: string[] = [];
    setImmediate(() => order.push("setImmediate-marker"));
    const turnEndPromise = (pi.handlers["turn_end"] ?? []).reduce<Promise<unknown>>(
      (p, h) => p.then(() => h({}, ctx)),
      Promise.resolve(),
    );
    order.push("after-call");
    await turnEndPromise;
    order.push("after-await");

    // After-call comes first (sync), then the setImmediate marker fires
    // (because turn_end yielded), then we resume after the await.
    expect(order[0]).toBe("after-call");
    // marker must appear before resolve completes
    expect(order).toContain("setImmediate-marker");
    expect(pi.followUps.length).toBe(1);
  });
});
