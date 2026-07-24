import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

// A fence around the #73 fix.
//
// Appending to the system prompt from `before_agent_start` invalidates the
// whole cached prefix, and the symptom is invisible from inside little-coder —
// it shows up as llama.cpp silently reprocessing 120k of history. It took an
// external tool (`cache-hunter`) for manueloverride to spot it at all.
//
// So rather than trusting that nobody re-adds the pattern, assert it: every
// extension must route its per-turn injection through `_shared/inject.ts`,
// which owns the one place that decides message-vs-system-prompt.

const extensionsDir = join(dirname(fileURLToPath(import.meta.url)), "..");

function extensionSources(): Array<{ name: string; src: string }> {
  return readdirSync(extensionsDir)
    .filter((name) => name !== "_shared")
    .map((name) => ({ name, path: join(extensionsDir, name, "index.ts") }))
    .filter((e) => existsSync(e.path))
    .map((e) => ({ name: e.name, src: readFileSync(e.path, "utf-8") }));
}

// `return { systemPrompt: … }` / `return {\n  systemPrompt: … }`, which is how
// every pre-v1.12.0 injector handed its block back to pi.
const RAW_SYSTEM_PROMPT_RETURN = /return\s*\{\s*systemPrompt\s*:/;

describe("per-turn injection never rewrites the system prompt (issue #73)", () => {
  it("no extension returns a raw systemPrompt from before_agent_start", () => {
    const offenders = extensionSources()
      .filter((e) => RAW_SYSTEM_PROMPT_RETURN.test(e.src))
      .map((e) => e.name);

    expect(
      offenders,
      `${offenders.join(", ")} returns a rewritten system prompt directly. That ` +
        `invalidates the KV cache for the entire conversation on every turn — use ` +
        `injectionResult() from _shared/inject.ts instead.`,
    ).toEqual([]);
  });

  it("every injector goes through injectionResult()", () => {
    const injectors = ["skill-inject", "knowledge-inject", "plan-mode", "deep-research"];
    const sources = new Map(extensionSources().map((e) => [e.name, e.src]));

    for (const name of injectors) {
      const src = sources.get(name);
      expect(src, `${name}/index.ts is missing`).toBeDefined();
      expect(src, `${name} should import from _shared/inject.ts`).toContain(
        "../_shared/inject.ts",
      );
      expect(src, `${name} should call injectionResult()`).toContain("injectionResult(");
    }
  });

  it("each injector uses its own customType so blocks stay distinguishable", () => {
    const sources = new Map(extensionSources().map((e) => [e.name, e.src]));
    const expected: Record<string, string> = {
      "skill-inject": "lc-skills",
      "knowledge-inject": "lc-knowledge",
      "plan-mode": "lc-plan",
      "deep-research": "lc-research",
    };
    for (const [name, customType] of Object.entries(expected)) {
      expect(sources.get(name), name).toContain(`"${customType}"`);
    }
  });
});
