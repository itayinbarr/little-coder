import { describe, it, expect, vi } from "vitest";
import setupWatchdog, {
  thresholdPercent,
  shouldCompactNow,
  compactionHelped,
  canCompactMidRun,
  classifyCompactionError,
  MIN_PROGRESS_PCT,
  RESUME_MESSAGE,
  type ContextUsageLike,
} from "./index.ts";

describe("thresholdPercent", () => {
  it("defaults to 80 when unset", () => {
    expect(thresholdPercent({})).toBe(80);
    expect(thresholdPercent({ LITTLE_CODER_COMPACT_AT_PERCENT: "  " })).toBe(80);
  });

  it("honors a valid override", () => {
    expect(thresholdPercent({ LITTLE_CODER_COMPACT_AT_PERCENT: "70" })).toBe(70);
    expect(thresholdPercent({ LITTLE_CODER_COMPACT_AT_PERCENT: "92.5" })).toBe(92.5);
  });

  it("treats non-numeric as the default", () => {
    expect(thresholdPercent({ LITTLE_CODER_COMPACT_AT_PERCENT: "soon" })).toBe(80);
  });

  it("disables for out-of-band values (<=0 or >=100)", () => {
    expect(thresholdPercent({ LITTLE_CODER_COMPACT_AT_PERCENT: "0" })).toBe(0);
    expect(thresholdPercent({ LITTLE_CODER_COMPACT_AT_PERCENT: "-5" })).toBe(0);
    expect(thresholdPercent({ LITTLE_CODER_COMPACT_AT_PERCENT: "100" })).toBe(0);
    expect(thresholdPercent({ LITTLE_CODER_COMPACT_AT_PERCENT: "150" })).toBe(0);
  });

  it("hard-off via LITTLE_CODER_NO_COMPACT_WATCHDOG=1 overrides a percent", () => {
    expect(
      thresholdPercent({
        LITTLE_CODER_NO_COMPACT_WATCHDOG: "1",
        LITTLE_CODER_COMPACT_AT_PERCENT: "70",
      }),
    ).toBe(0);
  });
});

describe("shouldCompactNow", () => {
  const usage = (over: Partial<ContextUsageLike>): ContextUsageLike => ({
    tokens: 50000,
    contextWindow: 64000,
    percent: 78,
    ...over,
  });

  it("fires once usage is at/above the threshold", () => {
    expect(shouldCompactNow(usage({ percent: 80 }), 80, false)).toBe(true);
    expect(shouldCompactNow(usage({ percent: 95 }), 80, false)).toBe(true);
  });

  it("does not fire below the threshold", () => {
    expect(shouldCompactNow(usage({ percent: 79 }), 80, false)).toBe(false);
  });

  it("never fires while a compaction is already in flight", () => {
    expect(shouldCompactNow(usage({ percent: 99 }), 80, true)).toBe(false);
  });

  it("no-ops on unknown token usage (null right after compaction)", () => {
    expect(shouldCompactNow(usage({ tokens: null, percent: null }), 80, false)).toBe(false);
  });

  it("no-ops when disabled (pct<=0) or usage missing / window unknown", () => {
    expect(shouldCompactNow(usage({ percent: 99 }), 0, false)).toBe(false);
    expect(shouldCompactNow(undefined, 80, false)).toBe(false);
    expect(shouldCompactNow(usage({ contextWindow: 0 }), 80, false)).toBe(false);
  });

  it("reproduces #59 followup: after compaction, the run is resumed (not stranded at the prompt)", async () => {
    // Wire up the real extension against a mock pi/ctx and drive one turn_start
    // over the threshold. The key regression: pi's threshold compaction aborts
    // the run and does NOT auto-continue, so without a resume the task stalls.
    const env = process.env.LITTLE_CODER_COMPACT_AT_PERCENT;
    process.env.LITTLE_CODER_COMPACT_AT_PERCENT = "80";
    try {
      const handlers: Record<string, Function> = {};
      const sendUserMessage = vi.fn();
      const pi = {
        on: (evt: string, h: Function) => { handlers[evt] = h; },
        sendUserMessage,
      };
      setupWatchdog(pi as any);

      let capturedOpts: any;
      const ctx = {
        mode: "tui",
        getContextUsage: () => ({ tokens: 52000, contextWindow: 64000, percent: 81 }),
        ui: { notify: vi.fn() },
        compact: (opts: any) => { capturedOpts = opts; },
      };

      await handlers.turn_start({}, ctx);
      // Compaction was requested with completion callbacks…
      expect(capturedOpts).toBeTruthy();
      expect(typeof capturedOpts.onComplete).toBe("function");
      // …and nothing is sent until compaction actually finishes.
      expect(sendUserMessage).not.toHaveBeenCalled();

      // Simulate pi finishing the compaction (agent reconnected + idle).
      capturedOpts.onComplete();
      expect(sendUserMessage).toHaveBeenCalledTimes(1);
      expect(sendUserMessage).toHaveBeenCalledWith(RESUME_MESSAGE, { deliverAs: "followUp" });
    } finally {
      if (env === undefined) delete process.env.LITTLE_CODER_COMPACT_AT_PERCENT;
      else process.env.LITTLE_CODER_COMPACT_AT_PERCENT = env;
    }
  });

  it("does not re-fire while a compaction is mid-flight, then re-arms after a compaction that freed headroom", async () => {
    const env = process.env.LITTLE_CODER_COMPACT_AT_PERCENT;
    process.env.LITTLE_CODER_COMPACT_AT_PERCENT = "80";
    try {
      const handlers: Record<string, Function> = {};
      const sendUserMessage = vi.fn();
      const pi = { on: (e: string, h: Function) => { handlers[e] = h; }, sendUserMessage };
      setupWatchdog(pi as any);

      // Mutable usage so we can model a compaction that actually frees space:
      // 81% → compact → 40% (helped) → climbs back to 81% → fires again.
      let percent = 81;
      const compact = vi.fn();
      const ctx = {
        mode: "tui",
        getContextUsage: () => ({ tokens: 52000, contextWindow: 64000, percent }),
        ui: { notify: vi.fn() },
        compact,
      };

      await handlers.turn_start({}, ctx);       // fires
      await handlers.turn_start({}, ctx);       // guarded — still mid-flight
      expect(compact).toHaveBeenCalledTimes(1);

      percent = 40;                             // compaction opened real headroom
      compact.mock.calls[0][0].onComplete();    // done, re-armed
      await handlers.turn_start({}, ctx);       // measures 40% (helped) — no fire
      expect(compact).toHaveBeenCalledTimes(1);

      percent = 81;                             // context climbed again
      await handlers.turn_start({}, ctx);       // fires again
      expect(compact).toHaveBeenCalledTimes(2);
    } finally {
      if (env === undefined) delete process.env.LITTLE_CODER_COMPACT_AT_PERCENT;
      else process.env.LITTLE_CODER_COMPACT_AT_PERCENT = env;
    }
  });

  it("#68: pauses instead of looping when a compaction frees too little, then re-arms on recovery", async () => {
    const env = process.env.LITTLE_CODER_COMPACT_AT_PERCENT;
    process.env.LITTLE_CODER_COMPACT_AT_PERCENT = "80";
    try {
      const handlers: Record<string, Function> = {};
      const sendUserMessage = vi.fn();
      const pi = { on: (e: string, h: Function) => { handlers[e] = h; }, sendUserMessage };
      setupWatchdog(pi as any);

      // The #68 shape: after compaction the resumed run re-reads files and usage
      // is STILL over threshold. A blind watchdog would fire compact() again into
      // "Nothing to compact"; the guard must pause instead.
      let percent = 92;
      const compact = vi.fn();
      const notify = vi.fn();
      const ctx = {
        mode: "tui",
        getContextUsage: () => ({ tokens: 59000, contextWindow: 64000, percent }),
        ui: { notify },
        compact,
      };

      await handlers.turn_start({}, ctx);       // fires the first compaction
      expect(compact).toHaveBeenCalledTimes(1);

      percent = 90;                             // freed almost nothing (still >> threshold)
      compact.mock.calls[0][0].onComplete();
      await handlers.turn_start({}, ctx);       // measures 90% → pause, NO second fire
      expect(compact).toHaveBeenCalledTimes(1);
      expect(notify).toHaveBeenCalledWith(
        expect.stringContaining("paused to avoid a loop"),
        "warning",
      );

      // Stays paused while still over the band, even as turns keep coming.
      await handlers.turn_start({}, ctx);
      await handlers.turn_start({}, ctx);
      expect(compact).toHaveBeenCalledTimes(1);

      // Manual recovery (/clear) drops usage below the band → re-arms and fires.
      percent = 40;
      await handlers.turn_start({}, ctx);       // re-arm turn (below band)
      percent = 85;                             // climbs back over threshold
      await handlers.turn_start({}, ctx);       // fires again
      expect(compact).toHaveBeenCalledTimes(2);
    } finally {
      if (env === undefined) delete process.env.LITTLE_CODER_COMPACT_AT_PERCENT;
      else process.env.LITTLE_CODER_COMPACT_AT_PERCENT = env;
    }
  });

  it("#68: a failed compaction (onError) pauses rather than silently retrying", async () => {
    const env = process.env.LITTLE_CODER_COMPACT_AT_PERCENT;
    process.env.LITTLE_CODER_COMPACT_AT_PERCENT = "80";
    try {
      const handlers: Record<string, Function> = {};
      const pi = { on: (e: string, h: Function) => { handlers[e] = h; }, sendUserMessage: vi.fn() };
      setupWatchdog(pi as any);

      const compact = vi.fn();
      const notify = vi.fn();
      const ctx = {
        mode: "tui",
        getContextUsage: () => ({ tokens: 59000, contextWindow: 64000, percent: 92 }),
        ui: { notify },
        compact,
      };

      await handlers.turn_start({}, ctx);
      expect(compact).toHaveBeenCalledTimes(1);

      // pi throws "Nothing to compact" — the guard must pause, not retry.
      compact.mock.calls[0][0].onError(new Error("Nothing to compact"));
      expect(notify).toHaveBeenCalledWith(
        expect.stringContaining("Nothing to compact"),
        "warning",
      );

      await handlers.turn_start({}, ctx);
      await handlers.turn_start({}, ctx);
      expect(compact).toHaveBeenCalledTimes(1); // still paused, never re-fired
    } finally {
      if (env === undefined) delete process.env.LITTLE_CODER_COMPACT_AT_PERCENT;
      else process.env.LITTLE_CODER_COMPACT_AT_PERCENT = env;
    }
  });

  describe("canCompactMidRun", () => {
    it("is true only for the TUI", () => {
      expect(canCompactMidRun("tui")).toBe(true);
      expect(canCompactMidRun("print")).toBe(false);
      expect(canCompactMidRun("json")).toBe(false);
      expect(canCompactMidRun("rpc")).toBe(false);
      expect(canCompactMidRun(undefined)).toBe(false);
    });
  });

  it("#115: headless never fires the mid-run compaction that aborts the run", async () => {
    const env = process.env.LITTLE_CODER_COMPACT_AT_PERCENT;
    process.env.LITTLE_CODER_COMPACT_AT_PERCENT = "80";
    try {
      for (const mode of ["print", "json", "rpc"]) {
        const handlers: Record<string, Function> = {};
        const pi = { on: (e: string, h: Function) => { handlers[e] = h; }, sendUserMessage: vi.fn() };
        setupWatchdog(pi as any);

        const compact = vi.fn();
        const ctx = {
          mode,
          getContextUsage: () => ({ tokens: 59000, contextWindow: 64000, percent: 92 }),
          ui: { notify: vi.fn() },
          compact,
        };

        // Well over threshold, and in the TUI this fires. Under -p, compact()
        // aborts the run print-mode is awaiting and the answer is lost.
        await handlers.turn_start({}, ctx);
        expect(compact, `mode=${mode}`).not.toHaveBeenCalled();
      }
    } finally {
      if (env === undefined) delete process.env.LITTLE_CODER_COMPACT_AT_PERCENT;
      else process.env.LITTLE_CODER_COMPACT_AT_PERCENT = env;
    }
  });

  it("#115: headless queues a continuation when pi compacts on its own", async () => {
    const handlers: Record<string, Function> = {};
    const sendUserMessage = vi.fn();
    const pi = { on: (e: string, h: Function) => { handlers[e] = h; }, sendUserMessage };
    setupWatchdog(pi as any);

    // pi's threshold compaction ends with `return this.agent.hasQueuedMessages()`,
    // which the caller turns into agent.continue(). The queued message is the
    // only thing that keeps a headless run alive across a compaction.
    await handlers.session_compact({ reason: "threshold", willRetry: false }, { mode: "print" });
    expect(sendUserMessage).toHaveBeenCalledWith(RESUME_MESSAGE, { deliverAs: "followUp" });
  });

  it("#115: does not queue on overflow recovery (pi retries that turn itself)", async () => {
    const handlers: Record<string, Function> = {};
    const sendUserMessage = vi.fn();
    const pi = { on: (e: string, h: Function) => { handlers[e] = h; }, sendUserMessage };
    setupWatchdog(pi as any);

    await handlers.session_compact({ reason: "overflow", willRetry: true }, { mode: "print" });
    expect(sendUserMessage).not.toHaveBeenCalled();
  });

  it("#115: the TUI does not double-resume (its own callback already does)", async () => {
    const handlers: Record<string, Function> = {};
    const sendUserMessage = vi.fn();
    const pi = { on: (e: string, h: Function) => { handlers[e] = h; }, sendUserMessage };
    setupWatchdog(pi as any);

    await handlers.session_compact({ reason: "threshold", willRetry: false }, { mode: "tui" });
    expect(sendUserMessage).not.toHaveBeenCalled();
  });

  describe("classifyCompactionError", () => {
    it("reads 'Already compacted' as another compaction having landed", () => {
      expect(classifyCompactionError("Already compacted")).toBe("already");
      expect(classifyCompactionError("Compaction failed: Already compacted")).toBe("already");
    });

    it("reads an abort/cancel as neither a failure nor a success", () => {
      expect(classifyCompactionError("Compaction cancelled")).toBe("cancelled");
      expect(classifyCompactionError("The operation was aborted")).toBe("cancelled");
    });

    it("reads everything else as a real failure", () => {
      expect(classifyCompactionError("Nothing to compact (session too small)")).toBe("failed");
      expect(classifyCompactionError(undefined)).toBe("failed");
      expect(classifyCompactionError("fetch failed")).toBe("failed");
    });
  });

  it("#109/#91: 'Already compacted' resumes the run instead of pausing", async () => {
    const env = process.env.LITTLE_CODER_COMPACT_AT_PERCENT;
    process.env.LITTLE_CODER_COMPACT_AT_PERCENT = "80";
    try {
      const handlers: Record<string, Function> = {};
      const sendUserMessage = vi.fn();
      const pi = { on: (e: string, h: Function) => { handlers[e] = h; }, sendUserMessage };
      setupWatchdog(pi as any);

      let percent = 88;
      const compact = vi.fn();
      const notify = vi.fn();
      const ctx = {
        mode: "tui",
        getContextUsage: () => ({ tokens: 56000, contextWindow: 64000, percent }),
        ui: { notify },
        compact,
      };

      await handlers.turn_start({}, ctx);
      expect(compact).toHaveBeenCalledTimes(1);

      // pi's own compaction landed first, so ours is refused. guppy42's report:
      // the run halted here and had to be restarted by typing "resume".
      compact.mock.calls[0][0].onError(new Error("Already compacted"));

      expect(sendUserMessage).toHaveBeenCalledWith(RESUME_MESSAGE, { deliverAs: "followUp" });
      expect(notify).not.toHaveBeenCalledWith(
        expect.stringContaining("could not proceed"),
        "warning",
      );

      // Armed, not paused: once the compacted context climbs back over the
      // threshold the watchdog still does its job.
      percent = 40;
      await handlers.before_agent_start({}, ctx);
      await handlers.turn_start({}, ctx);   // measures 40%, the compaction helped
      percent = 88;
      await handlers.turn_start({}, ctx);
      expect(compact).toHaveBeenCalledTimes(2);
    } finally {
      if (env === undefined) delete process.env.LITTLE_CODER_COMPACT_AT_PERCENT;
      else process.env.LITTLE_CODER_COMPACT_AT_PERCENT = env;
    }
  });

  it("#108: a compaction settling after the session is gone never throws", async () => {
    const env = process.env.LITTLE_CODER_COMPACT_AT_PERCENT;
    process.env.LITTLE_CODER_COMPACT_AT_PERCENT = "80";
    try {
      const handlers: Record<string, Function> = {};
      // pi invalidates the whole extension runtime on dispose: the ctx.ui getter
      // and pi.sendUserMessage both throw from that point on. pi calls our
      // callbacks from a floating promise, so a throw here is an unhandled
      // rejection that exits the process: heinrichI's sub-coder crash.
      let live = true;
      const stale = () => { throw new Error("This extension ctx is stale after session replacement or reload."); };
      const notify = vi.fn(() => { if (!live) stale(); });
      const sendUserMessage = vi.fn(() => { if (!live) stale(); });
      const pi = { on: (e: string, h: Function) => { handlers[e] = h; }, sendUserMessage };
      setupWatchdog(pi as any);

      const compact = vi.fn();
      const ctx = {
        mode: "tui",
        getContextUsage: () => ({ tokens: 59000, contextWindow: 64000, percent: 92 }),
        get ui() { if (!live) stale(); return { notify }; },
        compact,
      };

      await handlers.turn_start({}, ctx);
      expect(compact).toHaveBeenCalledTimes(1);

      live = false; // headless -p disposed the session the moment it settled

      // Each of the three outcomes must survive a dead session.
      expect(() => compact.mock.calls[0][0].onComplete()).not.toThrow();
      expect(() => compact.mock.calls[0][0].onError(new Error("Compaction cancelled"))).not.toThrow();
      expect(() => compact.mock.calls[0][0].onError(new Error("Nothing to compact (session too small)"))).not.toThrow();
      expect(() => compact.mock.calls[0][0].onError(new Error("Already compacted"))).not.toThrow();
    } finally {
      if (env === undefined) delete process.env.LITTLE_CODER_COMPACT_AT_PERCENT;
      else process.env.LITTLE_CODER_COMPACT_AT_PERCENT = env;
    }
  });

  it("#108: a cancelled compaction is silent and leaves the watchdog armed", async () => {
    const env = process.env.LITTLE_CODER_COMPACT_AT_PERCENT;
    process.env.LITTLE_CODER_COMPACT_AT_PERCENT = "80";
    try {
      const handlers: Record<string, Function> = {};
      const sendUserMessage = vi.fn();
      const pi = { on: (e: string, h: Function) => { handlers[e] = h; }, sendUserMessage };
      setupWatchdog(pi as any);

      const compact = vi.fn();
      const notify = vi.fn();
      const ctx = {
        mode: "tui",
        getContextUsage: () => ({ tokens: 59000, contextWindow: 64000, percent: 92 }),
        ui: { notify },
        compact,
      };

      await handlers.turn_start({}, ctx);
      compact.mock.calls[0][0].onError(new Error("Compaction cancelled"));

      // No warning, no resume: an abort is not a failure to report.
      expect(notify).not.toHaveBeenCalledWith(expect.anything(), "warning");
      expect(sendUserMessage).not.toHaveBeenCalled();

      // Still armed: the next over-threshold turn fires again.
      await handlers.turn_start({}, ctx);
      expect(compact).toHaveBeenCalledTimes(2);
    } finally {
      if (env === undefined) delete process.env.LITTLE_CODER_COMPACT_AT_PERCENT;
      else process.env.LITTLE_CODER_COMPACT_AT_PERCENT = env;
    }
  });

  it("a turn boundary during an in-flight compaction does not let a second one fire", async () => {
    const env = process.env.LITTLE_CODER_COMPACT_AT_PERCENT;
    process.env.LITTLE_CODER_COMPACT_AT_PERCENT = "80";
    try {
      const handlers: Record<string, Function> = {};
      const pi = { on: (e: string, h: Function) => { handlers[e] = h; }, sendUserMessage: vi.fn() };
      setupWatchdog(pi as any);

      const compact = vi.fn();
      const ctx = {
        mode: "tui",
        getContextUsage: () => ({ tokens: 56000, contextWindow: 64000, percent: 88 }),
        ui: { notify: vi.fn() },
        compact,
      };

      await handlers.turn_start({}, ctx);
      expect(compact).toHaveBeenCalledTimes(1);

      // pi's compact() aborts the run and reconnects the agent while it is still
      // summarizing, so a fresh turn can begin mid-compaction. Dropping the
      // in-flight flag there is what let a second call fire on top of the first
      // The loser of that race is the "Already compacted" in #109.
      await handlers.before_agent_start({}, ctx);
      await handlers.turn_start({}, ctx);
      expect(compact).toHaveBeenCalledTimes(1);

      // Once it settles, a later boundary is free to clear the flag again.
      compact.mock.calls[0][0].onComplete();
      await handlers.before_agent_start({}, ctx);
      await handlers.turn_start({}, ctx);   // measures 88% (helped nothing) → pause
      expect(compact).toHaveBeenCalledTimes(1);
    } finally {
      if (env === undefined) delete process.env.LITTLE_CODER_COMPACT_AT_PERCENT;
      else process.env.LITTLE_CODER_COMPACT_AT_PERCENT = env;
    }
  });

  describe("compactionHelped", () => {
    it("helped only when usage drops at least MIN_PROGRESS below the threshold", () => {
      expect(compactionHelped(80, 80)).toBe(false);            // still at threshold
      expect(compactionHelped(90, 80)).toBe(false);            // still over
      expect(compactionHelped(80 - MIN_PROGRESS_PCT + 1, 80)).toBe(false); // barely under
      expect(compactionHelped(80 - MIN_PROGRESS_PCT, 80)).toBe(true);      // at the band edge
      expect(compactionHelped(40, 80)).toBe(true);             // comfortable headroom
    });
  });

  it("reproduces #59: a run climbing 34k→64k on a 64k window compacts before overflow", () => {
    const window = 64000;
    const pct = 80; // fires at 51.2k, ~13k of headroom before the 64k overflow
    let compacting = false;
    let firstCompactAt: number | null = null;
    for (const tokens of [34472, 40829, 46990, 52048, 55461, 58076, 62572]) {
      const u = usage({ tokens, contextWindow: window, percent: (tokens / window) * 100 });
      if (shouldCompactNow(u, pct, compacting)) {
        compacting = true; // pi compaction now in flight for the rest of the run
        if (firstCompactAt === null) firstCompactAt = tokens;
      }
    }
    expect(firstCompactAt).toBe(52048); // first turn past 80% — well before 64k
  });
});
