import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const settingsPath = join(here, "..", "..", "settings.json");

// Mirror the resolution logic so we can test it as a pure function without
// instantiating the extension.
interface ModelProfile {
  thinking_budget?: number;
  max_turns?: number;
  temperature?: number;
  context_limit?: number;
  benchmark_overrides?: Record<string, Partial<ModelProfile>>;
}

function resolveProfile(
  settings: { model_profiles?: Record<string, ModelProfile>; default_model_profile?: ModelProfile },
  key: string,
  benchmark?: string,
): ModelProfile {
  const profiles = settings.model_profiles ?? {};
  let base: ModelProfile | undefined = profiles[key];
  if (!base) {
    for (const [pattern, p] of Object.entries(profiles)) {
      if (key.startsWith(pattern)) { base = p; break; }
    }
  }
  if (!base) base = settings.default_model_profile ?? {};
  const { benchmark_overrides, ...basePlain } = { ...base };
  if (benchmark && benchmark_overrides && benchmark_overrides[benchmark]) {
    return { ...basePlain, ...benchmark_overrides[benchmark] };
  }
  return basePlain;
}

describe("benchmark-profiles resolution against real settings.json", () => {
  const settings = JSON.parse(readFileSync(settingsPath, "utf-8")).little_coder;

  it("resolves base profile for llamacpp/qwen3.6-35b-a3b", () => {
    const p = resolveProfile(settings, "llamacpp/qwen3.6-35b-a3b");
    expect(p.thinking_budget).toBe(2048);
    expect(p.context_limit).toBe(32768);
    expect(p.max_turns).toBeUndefined();
  });

  it("applies terminal_bench overrides", () => {
    const p = resolveProfile(settings, "llamacpp/qwen3.6-35b-a3b", "terminal_bench");
    expect(p.thinking_budget).toBe(3000);
    expect(p.temperature).toBe(0.2);
    expect(p.max_turns).toBe(40);
    // Non-overridden fields fall through from base
    expect(p.context_limit).toBe(32768);
  });

  it("applies gaia overrides", () => {
    const p = resolveProfile(settings, "llamacpp/qwen3.6-35b-a3b", "gaia");
    expect(p.thinking_budget).toBe(2000);
    expect(p.temperature).toBe(0.4);
    expect(p.max_turns).toBe(40);
    expect(p.context_limit).toBe(65536);
  });

  it("unknown model falls back to default_model_profile", () => {
    const p = resolveProfile(settings, "fake-provider/fake-model");
    // Default profile defined in settings.json
    expect(p.thinking_budget).toBe(2048);
    expect(p.context_limit).toBe(32768);
  });

  it("unknown benchmark name yields base profile unchanged", () => {
    const p = resolveProfile(settings, "llamacpp/qwen3.6-35b-a3b", "totally_made_up");
    expect(p.thinking_budget).toBe(2048);
    expect(p.max_turns).toBeUndefined();
  });
});
