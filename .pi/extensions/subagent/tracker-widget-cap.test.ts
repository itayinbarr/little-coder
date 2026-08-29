import { describe, it, expect, vi } from "vitest";
import { SubCoderTracker } from "./tracker.ts";

// pi slices a string-array widget to MAX_WIDGET_LINES (10) and appends
// "... (widget truncated)" past that — dropping rows from the END.
//
// `SubCoderTracker.begin()` appends to `this.order` and never resets it, so a
// session with several dispatch turns accumulates rows without bound. Once past
// the cap, pi's truncation would hide the sub-coders that are actually RUNNING
// behind a backlog of finished ones — the live view degrading exactly when
// there's most to look at.

const stripAnsi = (s: string) => s.replace(/\x1b\[[0-9;]*[a-zA-Z]/g, "");

function makeTracker() {
  let lines: string[] | undefined;
  const ctx = {
    hasUI: true,
    ui: {
      setWidget: (_k: string, l: string[] | undefined) => {
        if (l) lines = l;
      },
    },
  };
  return { tracker: new SubCoderTracker(ctx, { key: "t" }), get: () => lines ?? [] };
}

function result(id: string, label: string, exitCode: number) {
  return {
    id,
    label,
    task: "",
    exitCode,
    report: "",
    messages: [],
    stderr: "",
    usage: { input: 0, output: 0, cost: 0, turns: 0, contextTokens: 0 },
  };
}

describe("sub-coder tracker stays inside pi's widget cap", () => {
  it("never renders more than 10 lines, however many dispatches ran", () => {
    const { tracker, get } = makeTracker();
    // Five dispatch turns of four tasks each — 20 sub-coders in one session.
    for (let turn = 0; turn < 5; turn++) {
      const batch = [0, 1, 2, 3].map((i) => ({ id: `t${turn}-${i}`, label: `task-${turn}-${i}` }));
      tracker.begin(batch);
      tracker.update(batch.map((b) => result(b.id, b.label, 0)));
    }
    tracker.end(); // forces a final synchronous paint
    expect(get().length).toBeLessThanOrEqual(10);
  });

  it("keeps every RUNNING sub-coder visible and summarizes the rest", () => {
    const { tracker, get } = makeTracker();
    const finishedIds = Array.from({ length: 12 }, (_, i) => ({ id: `d${i}`, label: `done-${i}` }));
    tracker.begin(finishedIds);
    tracker.update(finishedIds.map((b) => result(b.id, b.label, 0)));

    const runningIds = [0, 1, 2].map((i) => ({ id: `r${i}`, label: `live-${i}` }));
    tracker.begin(runningIds);
    tracker.update([
      ...finishedIds.map((b) => result(b.id, b.label, 0)),
      ...runningIds.map((b) => result(b.id, b.label, -1)),
    ]);
    tracker.end();

    const text = get().map(stripAnsi).join("\n");
    for (const r of runningIds) {
      expect(text, `${r.label} must stay visible`).toContain(r.label);
    }
    expect(get().length).toBeLessThanOrEqual(10);
    expect(text).toMatch(/\+\d+ earlier sub-coders/);
  });

  it("still reports the true total in the header", () => {
    const { tracker, get } = makeTracker();
    const all = Array.from({ length: 15 }, (_, i) => ({ id: `x${i}`, label: `t${i}` }));
    tracker.begin(all);
    tracker.update(all.map((b) => result(b.id, b.label, 0)));
    tracker.end();
    // The count must reflect everything that ran, not just what fits.
    expect(stripAnsi(get()[0])).toContain("15/15 done");
  });

  it("shows all rows without a summary line when they fit", () => {
    const { tracker, get } = makeTracker();
    const few = [0, 1, 2, 3].map((i) => ({ id: `a${i}`, label: `task-${i}` }));
    tracker.begin(few);
    tracker.update(few.map((b) => result(b.id, b.label, 0)));
    tracker.end();

    const text = get().map(stripAnsi).join("\n");
    expect(get().length).toBe(5); // header + 4 rows
    expect(text).not.toContain("earlier sub-coders");
  });
});

describe("stale context (the #108 / #119 shape)", () => {
  const STALE = () => {
    throw new Error("This extension ctx is stale after session replacement or reload.");
  };

  // A tracker outlives the session whenever a dispatch is in flight and the
  // session is replaced under it: /new, /clear, or /implement since v1.18.0.
  // Its animation timer and its `end()` in the tool's finally both touch the
  // captured ctx, and every accessor on an invalidated ctx throws.
  const deadCtx = {
    get hasUI(): boolean { return STALE(); },
    get ui(): any { return STALE(); },
  };

  it("begin/update/end are all no-ops on a disposed session instead of throwing", () => {
    const t = new SubCoderTracker(deadCtx as any);
    expect(() => t.begin([{ id: "1", label: "a" }])).not.toThrow();
    expect(() => t.update([
      { id: "1", label: "a", exitCode: -1, report: "", errorMessage: "", usage: undefined } as any,
    ])).not.toThrow();
    expect(() => t.end()).not.toThrow();
  });

  it("still paints while the session is alive", () => {
    const setWidget = vi.fn();
    const t = new SubCoderTracker({ hasUI: true, ui: { setWidget } } as any);
    t.begin([{ id: "1", label: "a" }]);
    expect(setWidget).toHaveBeenCalled();
    t.end();
  });
});
