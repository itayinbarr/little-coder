import { describe, it, expect } from "vitest";
import {
  matchesPrefix,
  modelForPhase,
  parseModelRef,
  phaseSummary,
  resolvePhaseDefaults,
  shouldSwitch,
} from "./phases.ts";

describe("parseModelRef", () => {
  it("splits provider/id", () => {
    expect(parseModelRef("llamacpp/qwen3.6-35b-a3b")).toEqual({
      provider: "llamacpp",
      id: "qwen3.6-35b-a3b",
    });
  });
  it("rejects anything that is not exactly provider/id", () => {
    for (const bad of ["", "bare-id", "/leading", "trailing/", "a/b/c", 7, null, undefined]) {
      expect(parseModelRef(bad as any), String(bad)).toBeNull();
    }
  });
});

describe("resolvePhaseDefaults", () => {
  const shipped = { planModel: "llamacpp/big", actionModel: "llamacpp/small", handover: "manual" };

  it("falls back to the shipped file", () => {
    expect(resolvePhaseDefaults(shipped, undefined, {})).toEqual({
      planModel: "llamacpp/big",
      actionModel: "llamacpp/small",
      handover: "manual",
    });
  });

  it("lets the user file beat the shipped file", () => {
    const user = { planModel: "ollama/planner" };
    const d = resolvePhaseDefaults(shipped, user, {});
    expect(d.planModel).toBe("ollama/planner");
    expect(d.actionModel).toBe("llamacpp/small"); // untouched keys still fall through
  });

  it("lets env beat both", () => {
    const d = resolvePhaseDefaults(shipped, { planModel: "ollama/planner" }, {
      LITTLE_CODER_PLAN_MODEL: "lmstudio/env-planner",
      LITTLE_CODER_MODEL_HANDOVER: "auto",
    } as any);
    expect(d.planModel).toBe("lmstudio/env-planner");
    expect(d.handover).toBe("auto");
  });

  it("defaults handover to auto when nothing configures it", () => {
    expect(resolvePhaseDefaults({}, {}, {}).handover).toBe("auto");
  });

  // A typo must not silently disable a valid lower-precedence value — that
  // failure mode is invisible (you just quietly get the wrong model).
  it("ignores a malformed value and falls through to the next source", () => {
    const d = resolvePhaseDefaults(shipped, undefined, {
      LITTLE_CODER_PLAN_MODEL: "not-a-ref",
      LITTLE_CODER_MODEL_HANDOVER: "sometimes",
    } as any);
    expect(d.planModel).toBe("llamacpp/big");
    expect(d.handover).toBe("manual");
  });
});

describe("modelForPhase", () => {
  it("uses the tag when set", () => {
    expect(modelForPhase("plan", { planModel: "p/1", actionModel: "a/1" }, "cur/1")).toBe("p/1");
    expect(modelForPhase("action", { planModel: "p/1", actionModel: "a/1" }, "cur/1")).toBe("a/1");
  });

  // The ergonomic promise: configure nothing, change nothing.
  it("falls back to the active model when untagged", () => {
    expect(modelForPhase("plan", {}, "cur/1")).toBe("cur/1");
    expect(modelForPhase("action", {}, "cur/1")).toBe("cur/1");
  });

  // Setting a big planner must not drag implementation onto it too.
  it("does not let one phase's tag leak into the other", () => {
    expect(modelForPhase("action", { planModel: "big/1" }, "cur/1")).toBe("cur/1");
  });
});

describe("shouldSwitch", () => {
  it("switches when a tag differs from the active model", () => {
    expect(shouldSwitch("plan", { planModel: "p/1", handover: "auto" }, "cur/1")).toEqual({
      switch: true,
      to: "p/1",
    });
  });

  // The reload guard: identical weights must never be evicted and re-read.
  it("does not switch when the target is already active", () => {
    const r = shouldSwitch("plan", { planModel: "p/1", handover: "auto" }, "p/1");
    expect(r.switch).toBe(false);
  });

  it("never switches under manual handover", () => {
    const r = shouldSwitch("action", { actionModel: "a/1", handover: "manual" }, "cur/1");
    expect(r).toEqual({ switch: false, reason: "handover is manual" });
  });

  it("does not switch when the phase is untagged", () => {
    const r = shouldSwitch("action", { handover: "auto" }, "cur/1");
    expect(r.switch).toBe(false);
  });
});

describe("matchesPrefix", () => {
  it("matches on any substring, and on multiple terms in any order", () => {
    const m = "llamacpp/qwen3.6-35b-a3b";
    expect(matchesPrefix(m, "35b")).toBe(true);
    expect(matchesPrefix(m, "llama 35")).toBe(true);
    expect(matchesPrefix(m, "35 llama")).toBe(true);
    expect(matchesPrefix(m, "QWEN")).toBe(true);
    expect(matchesPrefix(m, "")).toBe(true);
    expect(matchesPrefix(m, "gemma")).toBe(false);
  });
});

describe("phaseSummary", () => {
  it("is undefined when nothing is configured, so no chrome appears", () => {
    expect(phaseSummary({ handover: "auto" })).toBeUndefined();
  });
  it("names both sides, and says when a side is untagged", () => {
    expect(phaseSummary({ planModel: "llamacpp/big", handover: "auto" })).toBe("plan big → act active");
  });
  it("flags manual handover", () => {
    const s = phaseSummary({ planModel: "l/big", actionModel: "l/small", handover: "manual" });
    expect(s).toBe("plan big → act small (manual)");
  });
});
