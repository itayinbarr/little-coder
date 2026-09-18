import { describe, it, expect, afterEach, vi } from "vitest";
import setupProvider from "./index.ts";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

// End-to-end test of the issue #54 swap-time re-probe: drive the real default
// export (which reads the shipped models.json, so `llamacpp` is present) with a
// fake pi and a stubbed global fetch, then fire a model_select to confirm the
// provider is re-registered with the fresh window and the user is notified.

function fakePi() {
  const registers: { name: string; ctx: number | undefined }[] = [];
  let modelSelect: ((event: any, ctx: any) => any) | undefined;
  const pi = {
    registerProvider(name: string, config: any) {
      registers.push({ name, ctx: config.models?.[0]?.contextWindow });
    },
    on(event: string, handler: (event: any, ctx: any) => any) {
      if (event === "model_select") modelSelect = handler;
    },
  };
  return { pi, registers, fire: (e: any, c: any) => modelSelect?.(e, c) };
}

// Return a stub `fetch` that yields a different n_ctx on each successive call,
// so the startup probe and the swap probe see different windows.
function fetchReturning(...nctxSequence: number[]) {
  let i = 0;
  return vi.fn(async () => {
    const n_ctx = nctxSequence[Math.min(i, nctxSequence.length - 1)];
    i++;
    return {
      ok: true,
      json: async () => ({ default_generation_settings: { n_ctx } }),
    } as any;
  });
}

describe("llama-cpp-provider swap re-probe (issue #54)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    delete process.env.LITTLE_CODER_NO_CTX_PROBE;
  });

  it("re-registers llamacpp with the new window and notifies on swap", async () => {
    vi.stubGlobal("fetch", fetchReturning(32768, 131072));
    const { pi, registers, fire } = fakePi();
    await setupProvider(pi as any);

    // Startup registered llamacpp at the first probed window.
    const startup = registers.filter((r) => r.name === "llamacpp");
    expect(startup.at(-1)?.ctx).toBe(32768);

    const notes: string[] = [];
    await fire(
      {
        model: { provider: "llamacpp", id: "qwen3.8-27b" },
        previousModel: { provider: "llamacpp", id: "qwen3.6-27b" },
        source: "cycle",
      },
      { ui: { notify: (m: string) => notes.push(m) } },
    );

    // Swap re-registered llamacpp at the new window, with a notice.
    expect(registers.filter((r) => r.name === "llamacpp").at(-1)?.ctx).toBe(131072);
    expect(notes).toEqual(["context window updated 32k → 128k"]);
  });

  it("does nothing when the window is unchanged after a swap", async () => {
    vi.stubGlobal("fetch", fetchReturning(65536, 65536));
    const { pi, registers, fire } = fakePi();
    await setupProvider(pi as any);
    const before = registers.filter((r) => r.name === "llamacpp").length;

    const notes: string[] = [];
    await fire(
      {
        model: { provider: "llamacpp", id: "qwen3.8-27b" },
        previousModel: { provider: "llamacpp", id: "qwen3.6-27b" },
        source: "cycle",
      },
      { ui: { notify: (m: string) => notes.push(m) } },
    );

    expect(registers.filter((r) => r.name === "llamacpp").length).toBe(before);
    expect(notes).toEqual([]);
  });

  it("ignores the initial selection (previousModel undefined) and non-llamacpp models", async () => {
    vi.stubGlobal("fetch", fetchReturning(32768, 131072));
    const { pi, registers, fire } = fakePi();
    await setupProvider(pi as any);
    const before = registers.filter((r) => r.name === "llamacpp").length;
    const notes: string[] = [];
    const ctx = { ui: { notify: (m: string) => notes.push(m) } };

    // Initial selection of a llamacpp model — previousModel undefined → skip.
    await fire({ model: { provider: "llamacpp", id: "m1" }, previousModel: undefined, source: "set" }, ctx);
    // Swap to a non-llamacpp model → skip.
    await fire({ model: { provider: "ollama", id: "q" }, previousModel: { provider: "llamacpp", id: "m1" }, source: "cycle" }, ctx);

    expect(registers.filter((r) => r.name === "llamacpp").length).toBe(before);
    expect(notes).toEqual([]);
  });

  it("does not register a model_select hook when probing is disabled", async () => {
    process.env.LITTLE_CODER_NO_CTX_PROBE = "1";
    vi.stubGlobal("fetch", fetchReturning(131072));
    const { pi, fire } = fakePi();
    await setupProvider(pi as any);
    // No handler captured → fire is a no-op returning undefined.
    expect(
      await fire(
        { model: { provider: "llamacpp", id: "qwen3.8-27b" }, previousModel: { provider: "llamacpp", id: "qwen3.6-27b" }, source: "cycle" },
        { ui: { notify: () => {} } },
      ),
    ).toBeUndefined();
  });
});

// ── issue #121, end to end: router mode registers per-model windows ─────────
describe("llama-cpp-provider router-mode startup (issue #121)", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    delete process.env.LITTLE_CODER_MODELS_FILE;
  });

  /** A llama-swap-shaped server: /props answers as the ROUTER (n_ctx 0, which
   *  is what made the old probe fall through), /v1/models carries the real
   *  per-preset windows. */
  function routerFetch() {
    return vi.fn(async (url: string) => {
      if (String(url).endsWith("/props")) {
        return { ok: true, json: async () => ({ default_generation_settings: { n_ctx: 0 } }) } as any;
      }
      return {
        ok: true,
        json: async () => ({
          data: [
            { id: "qwen-64k", status: { args: ["--ctx-size", "65536"] } },
            { id: "qwen-128k", meta: { n_ctx: 131072 } },
            { id: "qwen-256k", status: { args: ["--ctx-size", "262144"] } },
          ],
        }),
      } as any;
    });
  }

  function fakePiAll() {
    const registers: { name: string; models: any[] }[] = [];
    const pi = {
      registerProvider(name: string, config: any) {
        registers.push({ name, models: config.models ?? [] });
      },
      on() {},
    };
    return { pi, registers };
  }

  it("each declared preset keeps its own window, and the default is probed, not models[0]", async () => {
    // @araujoigor's arrangement exactly: 64k listed first, 128k the default.
    const dir = mkdtempSync(join(tmpdir(), "lc-router-"));
    try {
      writeFileSync(
        join(dir, "models.json"),
        JSON.stringify({
          default: "llamacpp/qwen-128k",
          providers: {
            llamacpp: {
              api: "openai-completions",
              baseUrl: "http://127.0.0.1:9931/v1",
              apiKey: "LLAMACPP_API_KEY",
              models: [{ id: "qwen-64k" }, { id: "qwen-128k" }, { id: "qwen-256k" }],
            },
          },
        }),
      );
      process.env.LITTLE_CODER_MODELS_FILE = join(dir, "models.json");
      vi.stubGlobal("fetch", routerFetch());

      const { pi, registers } = fakePiAll();
      await setupProvider(pi as any);

      const llamacpp = registers.filter((r) => r.name === "llamacpp").at(-1)!;
      const byId = Object.fromEntries(llamacpp.models.map((m: any) => [m.id, m.contextWindow]));
      expect(byId).toMatchObject({
        "qwen-64k": 65536,
        "qwen-128k": 131072,
        "qwen-256k": 262144,
      });
      // The regression this guards: every model stamped with the 64k preset's
      // window because the probe looked up models[0].
      expect(byId["qwen-128k"]).not.toBe(65536);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});
