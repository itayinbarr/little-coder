import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { mkdtempSync, rmSync, writeFileSync, mkdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import {
  applyEnvOverrides,
  fillModelDefaults,
  loadProviders,
  mergeProviders,
  resolveOverridePath,
  propsUrlFor,
  contextWindowFromProps,
  probeContextWindow,
  type ProviderEntry,
} from "./config.ts";

const sampleProvider = (baseUrl: string, modelId: string): ProviderEntry => ({
  api: "openai-completions",
  baseUrl,
  apiKey: "SAMPLE_KEY",
  models: [
    {
      id: modelId,
      name: modelId,
      reasoning: true,
      input: ["text"],
      contextWindow: 32768,
      maxTokens: 4096,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    },
  ],
});

describe("resolveOverridePath", () => {
  it("prefers LITTLE_CODER_MODELS_FILE", () => {
    expect(resolveOverridePath({ LITTLE_CODER_MODELS_FILE: "/explicit.json", HOME: "/h" })).toBe("/explicit.json");
  });
  it("falls back to XDG_CONFIG_HOME", () => {
    expect(resolveOverridePath({ XDG_CONFIG_HOME: "/xdg", HOME: "/h" })).toBe(join("/xdg", "little-coder", "models.json"),);
  });
  it("falls back to HOME/.config", () => {
    expect(resolveOverridePath({ HOME: "/h" })).toBe(join("/h", ".config", "little-coder", "models.json"),);
  });
  it("falls back to USERPROFILE/.config when HOME is absent", () => {
    expect(resolveOverridePath({ USERPROFILE: "/profile" })).toBe(join("/profile", ".config", "little-coder", "models.json"),);
  });
  it("returns undefined when neither is set", () => {
    expect(resolveOverridePath({})).toBeUndefined();
  });
});

describe("mergeProviders", () => {
  it("returns the package default unchanged when there's no override", () => {
    const pkg = { llamacpp: sampleProvider("http://a/v1", "m1") };
    expect(mergeProviders(pkg, undefined)).toEqual(pkg);
  });
  it("user provider replaces same-key package provider", () => {
    const pkg = { llamacpp: sampleProvider("http://a/v1", "pkg-model") };
    const user = { llamacpp: sampleProvider("http://b/v1", "user-model") };
    const merged = mergeProviders(pkg, user);
    expect(merged.llamacpp.baseUrl).toBe("http://b/v1");
    expect(merged.llamacpp.models[0].id).toBe("user-model");
  });
  it("user provider not in package is added", () => {
    const pkg = { llamacpp: sampleProvider("http://a/v1", "m1") };
    const user = { custom: sampleProvider("http://c/v1", "c1") };
    const merged = mergeProviders(pkg, user);
    expect(Object.keys(merged).sort()).toEqual(["custom", "llamacpp"]);
  });
  it("package providers without an override are kept as-is", () => {
    const pkg = {
      llamacpp: sampleProvider("http://a/v1", "m1"),
      ollama: sampleProvider("http://o/v1", "m2"),
    };
    const user = { llamacpp: sampleProvider("http://b/v1", "m1b") };
    const merged = mergeProviders(pkg, user);
    expect(merged.ollama.baseUrl).toBe("http://o/v1");
  });
});

describe("applyEnvOverrides", () => {
  it("LLAMACPP_BASE_URL overrides llamacpp baseUrl", () => {
    const providers = { llamacpp: sampleProvider("http://file/v1", "m1") };
    const out = applyEnvOverrides(providers, { LLAMACPP_BASE_URL: "http://env/v1" });
    expect(out.llamacpp.baseUrl).toBe("http://env/v1");
  });
  it("OLLAMA_BASE_URL overrides ollama baseUrl", () => {
    const providers = { ollama: sampleProvider("http://file/v1", "m2") };
    const out = applyEnvOverrides(providers, { OLLAMA_BASE_URL: "http://env/v1" });
    expect(out.ollama.baseUrl).toBe("http://env/v1");
  });
  it("LMSTUDIO_BASE_URL overrides lmstudio baseUrl", () => {
    const providers = { lmstudio: sampleProvider("http://127.0.0.1:1234/v1", "local-model") };
    const out = applyEnvOverrides(providers, { LMSTUDIO_BASE_URL: "http://127.0.0.1:5678/v1" });
    expect(out.lmstudio.baseUrl).toBe("http://127.0.0.1:5678/v1");
  });
  it("does not alter providers without a known env knob", () => {
    const providers = { custom: sampleProvider("http://file/v1", "m") };
    const out = applyEnvOverrides(providers, { LLAMACPP_BASE_URL: "http://env/v1" });
    expect(out.custom.baseUrl).toBe("http://file/v1");
  });
});

describe("loadProviders (filesystem)", () => {
  let dir: string;
  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), "lc-providers-"));
  });
  afterEach(() => {
    rmSync(dir, { recursive: true, force: true });
  });

  it("loads the package default when present", () => {
    writeFileSync(
      join(dir, "models.json"),
      JSON.stringify({ providers: { llamacpp: sampleProvider("http://a/v1", "m1") } }),
    );
    const result = loadProviders(dir, {});
    expect(Object.keys(result.providers)).toEqual(["llamacpp"]);
    expect(result.sources[0]).toMatchObject({ status: "ok" });
  });

  it("merges a user override file when LITTLE_CODER_MODELS_FILE points at one", () => {
    writeFileSync(
      join(dir, "models.json"),
      JSON.stringify({ providers: { llamacpp: sampleProvider("http://a/v1", "pkg") } }),
    );
    const userPath = join(dir, "user-models.json");
    writeFileSync(
      userPath,
      JSON.stringify({ providers: { llamacpp: sampleProvider("http://b/v1", "user") } }),
    );
    const result = loadProviders(dir, { LITTLE_CODER_MODELS_FILE: userPath });
    expect(result.providers.llamacpp.baseUrl).toBe("http://b/v1");
    expect(result.providers.llamacpp.models[0].id).toBe("user");
  });

  it("reports invalid JSON in the package default and returns empty providers", () => {
    writeFileSync(join(dir, "models.json"), "{ this is not json");
    const result = loadProviders(dir, {});
    expect(result.providers).toEqual({});
    expect(result.sources[0].status).toBe("invalid");
  });

  it("reports a missing user override without failing the load", () => {
    writeFileSync(
      join(dir, "models.json"),
      JSON.stringify({ providers: { llamacpp: sampleProvider("http://a/v1", "m1") } }),
    );
    const missing = join(dir, "no-such-dir", "models.json");
    const result = loadProviders(dir, { LITTLE_CODER_MODELS_FILE: missing });
    expect(result.providers.llamacpp.baseUrl).toBe("http://a/v1");
    expect(result.sources.find((s) => s.path === missing)?.status).toBe("missing");
  });

  it("env var still overrides baseUrl after merge", () => {
    writeFileSync(
      join(dir, "models.json"),
      JSON.stringify({ providers: { llamacpp: sampleProvider("http://file/v1", "m") } }),
    );
    const result = loadProviders(dir, { LLAMACPP_BASE_URL: "http://env/v1" });
    expect(result.providers.llamacpp.baseUrl).toBe("http://env/v1");
  });

  it("XDG_CONFIG_HOME overrides applied when no LITTLE_CODER_MODELS_FILE set", () => {
    writeFileSync(
      join(dir, "models.json"),
      JSON.stringify({ providers: { llamacpp: sampleProvider("http://a/v1", "pkg") } }),
    );
    const xdg = join(dir, "xdg");
    mkdirSync(join(xdg, "little-coder"), { recursive: true });
    writeFileSync(
      join(xdg, "little-coder", "models.json"),
      JSON.stringify({ providers: { llamacpp: sampleProvider("http://x/v1", "via-xdg") } }),
    );
    const result = loadProviders(dir, { XDG_CONFIG_HOME: xdg });
    expect(result.providers.llamacpp.models[0].id).toBe("via-xdg");
  });
});

describe("shipped models.json", () => {
  const here = dirname(fileURLToPath(import.meta.url));
  const pkgRoot = resolve(here, "..", "..", "..");

  it("registers lmstudio/local-model on http://127.0.0.1:1234/v1", () => {
    const result = loadProviders(pkgRoot, {});
    const lmstudio = result.providers.lmstudio;
    expect(lmstudio, "lmstudio provider should be present in shipped models.json").toBeDefined();
    expect(lmstudio.baseUrl).toBe("http://127.0.0.1:1234/v1");
    expect(lmstudio.api).toBe("openai-completions");
    expect(lmstudio.apiKey).toBe("LMSTUDIO_API_KEY");
    expect(lmstudio.models.find((m) => m.id === "local-model")).toBeDefined();
  });

  it("still registers llamacpp and ollama alongside lmstudio", () => {
    const result = loadProviders(pkgRoot, {});
    expect(Object.keys(result.providers).sort()).toEqual(["llamacpp", "lmstudio", "ollama"]);
  });
});

describe("fillModelDefaults (issue #36)", () => {
  // The crash was: a user models.json entry that omitted name/maxTokens/cost
  // reached pi's registry as `model.cost === undefined`, which then exploded
  // with "Cannot read properties of undefined (reading 'input')" deep in
  // applyModelOverride. Filling the same defaults pi uses internally lets a
  // minimal entry round-trip safely.
  it("fills name/maxTokens/cost/input/contextWindow/reasoning when missing", () => {
    const out = fillModelDefaults({ id: "foo.gguf" }, "llamacpp", 0);
    expect(out).toMatchObject({
      id: "foo.gguf",
      name: "foo.gguf",
      reasoning: false,
      input: ["text"],
      contextWindow: 32768,
      maxTokens: 4096,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    });
  });

  it("preserves user-supplied values over defaults", () => {
    const out = fillModelDefaults(
      {
        id: "Qwen3.6-27B-Q4_K_M.gguf",
        reasoning: true,
        input: ["text", "image"],
        contextWindow: 262144,
      },
      "llamacpp",
      0,
    );
    expect(out.reasoning).toBe(true);
    expect(out.input).toEqual(["text", "image"]);
    expect(out.contextWindow).toBe(262144);
    // Still defaulted:
    expect(out.maxTokens).toBe(4096);
    expect(out.cost).toEqual({ input: 0, output: 0, cacheRead: 0, cacheWrite: 0 });
  });

  it("preserves unknown extra fields (e.g. _launch)", () => {
    const out: any = fillModelDefaults({ id: "x", _launch: true }, "llamacpp", 0);
    expect(out._launch).toBe(true);
  });

  it("throws with a precise pointer when id is missing", () => {
    expect(() => fillModelDefaults({}, "llamacpp", 2)).toThrow(/provider 'llamacpp' model at index 2/);
    expect(() => fillModelDefaults({ id: "" }, "llamacpp", 0)).toThrow(/missing or invalid "id"/);
  });
});

describe("loadProviders with an under-specified user override (issue #36)", () => {
  let dir: string;
  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), "lc-providers36-"));
  });
  afterEach(() => {
    rmSync(dir, { recursive: true, force: true });
  });

  it("a minimal user model entry no longer leaves cost undefined", () => {
    writeFileSync(join(dir, "models.json"), JSON.stringify({ providers: {} }));
    const userPath = join(dir, "user.json");
    writeFileSync(
      userPath,
      JSON.stringify({
        providers: {
          llamacpp: {
            api: "openai-completions",
            apiKey: "llama",
            baseUrl: "http://127.0.0.1:8020/v1",
            models: [
              {
                _launch: true,
                contextWindow: 262144,
                id: "Qwen3.6-27B-Q4_K_M.gguf",
                input: ["text", "image"],
                reasoning: true,
              },
            ],
          },
        },
      }),
    );
    const result = loadProviders(dir, { LITTLE_CODER_MODELS_FILE: userPath });
    const m = result.providers.llamacpp.models[0];
    expect(m.cost).toEqual({ input: 0, output: 0, cacheRead: 0, cacheWrite: 0 });
    expect(m.maxTokens).toBe(4096);
    expect(m.name).toBe("Qwen3.6-27B-Q4_K_M.gguf");
    // User-supplied values must win:
    expect(m.contextWindow).toBe(262144);
    expect(m.input).toEqual(["text", "image"]);
  });

  it("a model entry without an id is reported as invalid, not silently passed through", () => {
    writeFileSync(join(dir, "models.json"), JSON.stringify({ providers: {} }));
    const userPath = join(dir, "user.json");
    writeFileSync(
      userPath,
      JSON.stringify({
        providers: {
          llamacpp: {
            api: "openai-completions",
            apiKey: "k",
            baseUrl: "http://x/v1",
            models: [{ reasoning: true }],
          },
        },
      }),
    );
    const result = loadProviders(dir, { LITTLE_CODER_MODELS_FILE: userPath });
    const userSrc = result.sources.find((s) => s.path === userPath);
    expect(userSrc?.status).toBe("invalid");
    expect(userSrc?.error).toMatch(/missing or invalid "id"/);
  });
});

describe("propsUrlFor", () => {
  it("strips a trailing /v1 and points at the server root /props", () => {
    expect(propsUrlFor("http://127.0.0.1:8888/v1")).toBe("http://127.0.0.1:8888/props");
    expect(propsUrlFor("http://host:8888/v1/")).toBe("http://host:8888/props");
    expect(propsUrlFor("http://host:8888")).toBe("http://host:8888/props");
    expect(propsUrlFor("http://host:8888/")).toBe("http://host:8888/props");
  });
});

describe("contextWindowFromProps", () => {
  it("reads default_generation_settings.n_ctx (real llama.cpp shape)", () => {
    expect(contextWindowFromProps({ default_generation_settings: { n_ctx: 131072 } })).toBe(131072);
  });
  it("falls back to a top-level n_ctx", () => {
    expect(contextWindowFromProps({ n_ctx: 65536 })).toBe(65536);
  });
  it("returns undefined when absent or non-positive", () => {
    expect(contextWindowFromProps({})).toBeUndefined();
    expect(contextWindowFromProps({ default_generation_settings: { n_ctx: 0 } })).toBeUndefined();
    expect(contextWindowFromProps({ default_generation_settings: { n_ctx: "lots" } })).toBeUndefined();
    expect(contextWindowFromProps(null)).toBeUndefined();
  });
});

describe("probeContextWindow", () => {
  const okRes = (body: unknown) => ({ ok: true, json: async () => body }) as Response;

  it("returns the server's n_ctx on success", async () => {
    const fetchImpl = (async () =>
      okRes({ default_generation_settings: { n_ctx: 131072 } })) as unknown as typeof fetch;
    expect(await probeContextWindow("http://x:8888/v1", { fetchImpl })).toBe(131072);
  });

  it("returns undefined on a non-OK response", async () => {
    const fetchImpl = (async () => ({ ok: false }) as Response) as unknown as typeof fetch;
    expect(await probeContextWindow("http://x:8888/v1", { fetchImpl })).toBeUndefined();
  });

  it("returns undefined when fetch throws (server down / unreachable)", async () => {
    const fetchImpl = (async () => {
      throw new Error("ECONNREFUSED");
    }) as unknown as typeof fetch;
    expect(await probeContextWindow("http://x:8888/v1", { fetchImpl })).toBeUndefined();
  });

  it("returns undefined when the response lacks n_ctx", async () => {
    const fetchImpl = (async () => okRes({ total_slots: 1 })) as unknown as typeof fetch;
    expect(await probeContextWindow("http://x:8888/v1", { fetchImpl })).toBeUndefined();
  });

  it("honors an explicit props url override", async () => {
    let seen = "";
    const fetchImpl = (async (u: string) => {
      seen = u;
      return okRes({ default_generation_settings: { n_ctx: 40960 } });
    }) as unknown as typeof fetch;
    const got = await probeContextWindow("http://x:8888/v1", { fetchImpl, url: "http://other/props" });
    expect(seen).toBe("http://other/props");
    expect(got).toBe(40960);
  });
});
