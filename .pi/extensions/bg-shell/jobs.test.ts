import { describe, it, expect } from "vitest";
import {
  LineBuffer,
  MIN_WAKE_INTERVAL_MS,
  compileMatcher,
  evaluateExit,
  evaluateMatch,
  evaluateSilence,
  findMatch,
  formatElapsed,
  formatWakePayload,
  laneDelivery,
  normalizeRules,
  parseDuration,
  wrapWithParentWatchdog,
  type JobWakeState,
} from "./jobs.ts";

const freshState = (over: Partial<JobWakeState> = {}): JobWakeState => ({
  matchCount: 0,
  lastWakeAt: 0,
  stallNotified: false,
  ...over,
});

describe("parseDuration", () => {
  it("parses the suffixed forms", () => {
    expect(parseDuration("500ms")).toBe(500);
    expect(parseDuration("45s")).toBe(45_000);
    expect(parseDuration("10m")).toBe(600_000);
    expect(parseDuration("2h")).toBe(7_200_000);
  });
  it("treats a bare number as seconds", () => {
    expect(parseDuration("30")).toBe(30_000);
    expect(parseDuration(30)).toBe(30_000);
  });
  // A typo must disable the rule, not silently mean "0ms" (= wake constantly).
  it("returns null for nonsense rather than zero", () => {
    for (const bad of ["", "soon", "-5s", "0", {}, null, undefined]) {
      expect(parseDuration(bad as any), String(bad)).toBeNull();
    }
  });
});

describe("normalizeRules", () => {
  it("defaults to waking on exit only", () => {
    expect(normalizeRules(undefined)).toEqual({ exit: true, match: [] });
  });
  it("accepts a single string or an array for match", () => {
    expect(normalizeRules({ match: "Traceback" }).match).toEqual(["Traceback"]);
    expect(normalizeRules({ match: ["a", "b"] }).match).toEqual(["a", "b"]);
  });
  it("accepts both snake_case and camelCase for every_n_matches", () => {
    expect(normalizeRules({ every_n_matches: 10 }).everyNMatches).toBe(10);
    expect(normalizeRules({ everyNMatches: 4 }).everyNMatches).toBe(4);
  });
  it("ignores a malformed field instead of failing the whole call", () => {
    const r = normalizeRules({ match: [1, "ok", null], silence: "later", every_n_matches: 1 });
    expect(r.match).toEqual(["ok"]);
    expect(r.silenceMs).toBeUndefined();
    expect(r.everyNMatches).toBeUndefined(); // N=1 is not a throttle
  });
  it("honours exit:false", () => {
    expect(normalizeRules({ exit: false }).exit).toBe(false);
  });
});

describe("compileMatcher", () => {
  it("treats a valid pattern as a case-insensitive regex", () => {
    expect(compileMatcher("val_loss=[0-9.]+")("  val_loss=0.31")).toBe(true);
    expect(compileMatcher("^Epoch")("Epoch 3/50")).toBe(true);
  });
  // Models write prose far more often than they write anchors.
  it("degrades an invalid regex to a literal substring rather than throwing", () => {
    const m = compileMatcher("CUDA out of memory (");
    expect(() => m("x")).not.toThrow();
    expect(m("RuntimeError: CUDA out of memory (tried to allocate)")).toBe(true);
  });
});

describe("LineBuffer", () => {
  it("keeps a stable total once old lines are dropped", () => {
    const b = new LineBuffer(3);
    for (let i = 0; i < 10; i++) b.push(`line${i}`);
    expect(b.total).toBe(10);
    expect(b.droppedCount).toBe(7);
    expect(b.tail(3)).toEqual(["line7", "line8", "line9"]);
  });
  it("clamps a slice that asks for dropped lines", () => {
    const b = new LineBuffer(3);
    for (let i = 0; i < 10; i++) b.push(`line${i}`);
    const s = b.slice(0, 2);
    expect(s.from).toBe(7); // clamped up to what is still retained
    expect(s.lines).toEqual(["line7", "line8"]);
    expect(s.nextOffset).toBe(9);
  });
});

describe("evaluateExit", () => {
  it("gives a crash the urgent lane and a clean exit the polite one", () => {
    expect(evaluateExit(1, { exit: true, match: [] })).toMatchObject({ kind: "exit", lane: "now" });
    expect(evaluateExit(0, { exit: true, match: [] })).toMatchObject({ kind: "exit", lane: "soon" });
  });
  it("stays silent when exit waking is off", () => {
    expect(evaluateExit(1, { exit: false, match: [] })).toBeNull();
  });
});

describe("findMatch + evaluateMatch", () => {
  const rules = { exit: true, match: ["Traceback", "val_loss="] };

  it("finds the matching pattern", () => {
    expect(findMatch("  Traceback (most recent call last)", rules)).toBe("Traceback");
    expect(findMatch("epoch 2 val_loss=0.4", rules)).toBe("val_loss=");
    expect(findMatch("all quiet", rules)).toBeNull();
  });

  it("routes an error-ish line to the urgent lane and a progress line to the polite one", () => {
    const now = MIN_WAKE_INTERVAL_MS * 10;
    const err = evaluateMatch("Traceback", "Traceback (most recent call last)", rules, freshState(), 1, now);
    expect(err).toMatchObject({ lane: "now" });
    const ok = evaluateMatch("val_loss=", "epoch 2 val_loss=0.4", rules, freshState(), 1, now);
    expect(ok).toMatchObject({ lane: "soon" });
  });

  // The whole point of the feature: a six-hour job must not produce a turn per line.
  it("throttles to every Nth match", () => {
    const r = { exit: true, match: ["step"], everyNMatches: 10 };
    const now = MIN_WAKE_INTERVAL_MS * 10;
    const woke: number[] = [];
    for (let i = 1; i <= 25; i++) {
      // lastWakeAt stays far in the past so only the throttle is under test
      if (evaluateMatch("step", `step ${i}`, r, freshState(), i, now)) woke.push(i);
    }
    expect(woke).toEqual([10, 20]);
  });

  // A job that matches its own error pattern every second must not drive the
  // agent in a loop.
  it("suppresses a second wake inside the minimum interval", () => {
    const now = 1_000_000;
    const state = freshState({ lastWakeAt: now - 1000 });
    expect(evaluateMatch("Traceback", "Traceback", rules, state, 1, now)).toBeNull();
    const later = freshState({ lastWakeAt: now - MIN_WAKE_INTERVAL_MS - 1 });
    expect(evaluateMatch("Traceback", "Traceback", rules, later, 1, now)).not.toBeNull();
  });
});

describe("evaluateSilence", () => {
  const rules = { exit: true, match: [], silenceMs: 60_000 };

  it("fires once the quiet period is exceeded", () => {
    const now = 500_000;
    expect(evaluateSilence(rules, freshState(), now - 61_000, now)).toMatchObject({
      kind: "silence",
      lane: "soon",
    });
  });
  it("stays quiet before the threshold", () => {
    const now = 500_000;
    expect(evaluateSilence(rules, freshState(), now - 10_000, now)).toBeNull();
  });
  it("does not re-fire for the same quiet period", () => {
    const now = 500_000;
    const state = freshState({ stallNotified: true });
    expect(evaluateSilence(rules, state, now - 61_000, now)).toBeNull();
  });
  // A job that is legitimately silent from the start (a long compile) is not stalled.
  it("does not fire for a job that has never produced output", () => {
    expect(evaluateSilence(rules, freshState(), null, 500_000)).toBeNull();
  });
});

describe("laneDelivery", () => {
  it("maps lanes onto pi's delivery modes", () => {
    expect(laneDelivery("now")).toEqual({ deliverAs: "steer", triggerTurn: true });
    expect(laneDelivery("soon")).toEqual({ deliverAs: "followUp", triggerTurn: true });
    expect(laneDelivery("idle")).toEqual({ deliverAs: "nextTurn" });
  });
});

describe("formatWakePayload", () => {
  const base = {
    id: "job1",
    label: "finetune",
    command: "python train.py",
    elapsedMs: 2_400_000,
    lines: ["epoch 3", "val_loss=0.4"],
    totalLines: 98_000,
  };

  it("is bounded: it reports the total but carries only the excerpt", () => {
    const out = formatWakePayload({
      ...base,
      event: { kind: "match", lane: "soon", reason: 'matched "val_loss="' },
    });
    expect(out).toContain("98000 lines");
    expect(out).toContain("val_loss=0.4");
    expect(out).not.toContain("epoch 1"); // never in `lines`, so never in the payload
    expect(out.length).toBeLessThan(2000);
  });

  it("points at ShellLog while the job is alive, and does not once it has exited", () => {
    const running = formatWakePayload({
      ...base,
      event: { kind: "match", lane: "soon", reason: "matched" },
    });
    expect(running).toContain("ShellLog");
    const done = formatWakePayload({
      ...base,
      exitCode: 0,
      event: { kind: "exit", lane: "soon", reason: "exited 0" },
    });
    expect(done).toContain("exit 0");
    expect(done).not.toContain("still running");
  });
});

describe("formatElapsed", () => {
  it("scales the unit to the magnitude", () => {
    expect(formatElapsed(5_000)).toBe("5s");
    expect(formatElapsed(125_000)).toBe("2m05s");
    expect(formatElapsed(7_500_000)).toBe("2h05m");
  });
});

describe("wrapWithParentWatchdog", () => {
  const wrapped = wrapWithParentWatchdog("python train.py", 4242, 5);

  it("polls the real parent pid and kills its own group", () => {
    expect(wrapped).toContain("__lc_parent=4242");
    expect(wrapped).toContain('kill -0 "$__lc_parent"');
    // `kill -TERM 0` targets the JOB's group — safe only because the job is
    // spawned detached. It must never be a bare pid that could be ours.
    expect(wrapped).toContain("kill -TERM 0");
  });

  it("runs the command and preserves its exit status", () => {
    expect(wrapped).toContain("python train.py");
    expect(wrapped).toContain("exit $__lc_rc");
  });

  it("stops the watchdog on the normal path so nothing is left behind", () => {
    expect(wrapped).toContain('kill "$__lc_watchdog"');
  });
});
