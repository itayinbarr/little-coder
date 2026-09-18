import { describe, it, expect } from "vitest";
import {
  CHARS_PER_TOKEN,
  charLength,
  estimateContextTokens,
  looksTruncated,
  reconcileUsage,
  reportsPostTruncationInput,
} from "./local-estimate.ts";

describe("which providers report post-truncation input (issue #128)", () => {
  it("ollama does. Measured: 159,062 chars sent, prompt_eval_count 16,386", () => {
    expect(reportsPostTruncationInput("ollama")).toBe(true);
    expect(reportsPostTruncationInput("Ollama")).toBe(true);
  });

  it("the providers that report honestly are left alone", () => {
    // Substituting an estimate for a correct reading only adds error.
    for (const p of ["llamacpp", "lmstudio", "mistral", undefined]) {
      expect(reportsPostTruncationInput(p)).toBe(false);
    }
  });

  it("the env var forces it either way", () => {
    expect(reportsPostTruncationInput("llamacpp", { LITTLE_CODER_LOCAL_CONTEXT_ESTIMATE: "1" })).toBe(true);
    expect(reportsPostTruncationInput("ollama", { LITTLE_CODER_LOCAL_CONTEXT_ESTIMATE: "off" })).toBe(false);
  });
});

describe("charLength", () => {
  it("counts strings anywhere in a nested structure", () => {
    expect(charLength([{ role: "user", content: [{ type: "text", text: "hello" }] }])).toBe(
      "user".length + "text".length + "hello".length,
    );
  });

  it("survives a shape it has never seen, since pi's entries change between releases", () => {
    // An estimate that silently returns 0 after a pi upgrade is worse than a
    // loose one, so the walk is generic rather than shape-matched.
    expect(charLength({ a: { b: { c: ["deep", 42, true] } } })).toBeGreaterThan(0);
  });

  it("returns 0 for nothing rather than throwing", () => {
    expect(charLength(null)).toBe(0);
    expect(charLength(undefined)).toBe(0);
  });

  it("does not recurse forever on a cyclic structure", () => {
    const a: any = { name: "x" };
    a.self = a;
    expect(() => charLength(a)).not.toThrow();
  });
});

describe("estimateContextTokens", () => {
  it("counts the entries and the system prompt together", () => {
    const entries = [{ text: "x".repeat(400) }];
    const sys = "y".repeat(400);
    expect(estimateContextTokens(entries, sys)).toBe(800 / CHARS_PER_TOKEN);
  });
});

describe("reconcileUsage", () => {
  const window = 32768;

  it("reproduces the reported failure: 50k tokens of prompt read back as 16k", () => {
    // brlucasdx's measurement. Reported usage sits at half the window and stops
    // climbing, so the 80% threshold is reached far too late.
    const reported = { tokens: 16386, contextWindow: window, percent: (16386 / window) * 100 };
    expect(reported.percent).toBeLessThan(80);

    const out = reconcileUsage(reported, 50000, true)!;
    expect(out.tokens).toBe(50000);
    expect(out.percent!).toBeGreaterThan(100);
  });

  it("leaves an honest provider's reading exactly as it found it", () => {
    const reported = { tokens: 16386, contextWindow: window, percent: 50 };
    expect(reconcileUsage(reported, 50000, false)).toBe(reported);
  });

  it("never moves compaction LATER; the estimate only ever wins when it is larger", () => {
    // The estimate omits tool schemas and per-message framing, so it is a lower
    // bound; taking the max is what makes substituting it safe.
    const reported = { tokens: 30000, contextWindow: window, percent: 91 };
    expect(reconcileUsage(reported, 12000, true)).toBe(reported);
  });

  it("handles the no-reading-yet state without inventing one", () => {
    expect(reconcileUsage(undefined, 50000, true)).toBeUndefined();
    const noWindow = { tokens: 100, contextWindow: 0, percent: null };
    expect(reconcileUsage(noWindow, 50000, true)).toBe(noWindow);
  });

  it("a null token count still gets the estimate, which is the truncation case", () => {
    const reported = { tokens: null, contextWindow: window, percent: null };
    expect(reconcileUsage(reported, 20000, true)!.tokens).toBe(20000);
  });
});

describe("looksTruncated", () => {
  it("fires on the reported signature: a reading pinned near half the prompt", () => {
    expect(looksTruncated(16386, 50000)).toBe(true);
  });

  it("stays quiet for ordinary estimation error", () => {
    expect(looksTruncated(30000, 31000)).toBe(false);
  });

  it("says nothing when there is no reading to compare against", () => {
    expect(looksTruncated(null, 50000)).toBe(false);
    expect(looksTruncated(0, 50000)).toBe(false);
  });
});
