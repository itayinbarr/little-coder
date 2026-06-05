// Pure config-loading logic for the providers extension. Kept separate from
// the pi wiring in index.ts so it can be unit-tested without a pi runtime.
//
// Schema (all required unless noted):
//   {
//     "providers": {
//       "<name>": {
//         "api": "openai-completions",
//         "baseUrl": "http://...",
//         "apiKey": "ENV_VAR_NAME",
//         "models": [ { id, name, reasoning, input, contextWindow, maxTokens, cost }, ... ]
//       }, ...
//     }
//   }

import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

export interface ProviderModelEntry {
  id: string;
  name: string;
  reasoning: boolean;
  input: ("text" | "image")[];
  contextWindow: number;
  maxTokens: number;
  cost: { input: number; output: number; cacheRead: number; cacheWrite: number };
}

export interface ProviderEntry {
  api: string;
  baseUrl: string;
  apiKey: string;
  models: ProviderModelEntry[];
}

export interface ModelsFile {
  providers: Record<string, ProviderEntry>;
}

export interface LoadResult {
  providers: Record<string, ProviderEntry>;
  /** Files that were attempted, in resolution order. Useful for diagnostics. */
  sources: { path: string; status: "ok" | "missing" | "invalid"; error?: string }[];
}

/** Provider env knob: if set, overrides the provider's baseUrl. Originally a
 *  back-compat shim for the two providers we shipped before the data-driven
 *  refactor; kept as the per-provider env-override pattern for any provider
 *  whose baseUrl changes between deployments. */
const LEGACY_BASE_URL_ENV: Record<string, string> = {
  llamacpp: "LLAMACPP_BASE_URL",
  ollama: "OLLAMA_BASE_URL",
  lmstudio: "LMSTUDIO_BASE_URL",
};

/** Resolution order for the user-override file. First existing path wins. */
export function resolveOverridePath(env: NodeJS.ProcessEnv = process.env): string | undefined {
  if (env.LITTLE_CODER_MODELS_FILE) return env.LITTLE_CODER_MODELS_FILE;
  const xdg = env.XDG_CONFIG_HOME;
  if (xdg) return join(xdg, "little-coder", "models.json");
  const home = env.HOME || env.USERPROFILE;
  if (home) return join(home, ".config", "little-coder", "models.json");
  return undefined;
}

function parseModelsFile(raw: string): ModelsFile {
  const parsed = JSON.parse(raw);
  if (!parsed || typeof parsed !== "object" || !parsed.providers || typeof parsed.providers !== "object") {
    throw new Error("expected top-level { providers: { ... } }");
  }
  const providers = parsed.providers as Record<string, ProviderEntry>;
  for (const [name, entry] of Object.entries(providers)) {
    if (!entry || typeof entry !== "object" || !Array.isArray(entry.models)) continue;
    entry.models = entry.models.map((m, i) => fillModelDefaults(m, name, i));
  }
  return parsed as ModelsFile;
}

/**
 * Fill in defaults for optional model fields that pi requires downstream.
 * pi's `registerProvider` path stores model entries verbatim, so a user
 * override that omits e.g. `cost` ends up with `model.cost === undefined`,
 * and the model registry's per-model override path crashes with
 * "Cannot read properties of undefined (reading 'input')" (issue #36) when
 * it tries to read `model.cost.input`. Filling the same defaults pi uses
 * for built-in models means a minimal user entry — just an id — works.
 *
 * The `id` field is the only true requirement. We throw with a precise
 * pointer when it's missing so the caller can route this to the source-list
 * diagnostics rather than crashing pi.
 */
export function fillModelDefaults(m: any, providerName: string, index: number): ProviderModelEntry {
  if (!m || typeof m !== "object" || typeof m.id !== "string" || m.id.length === 0) {
    throw new Error(`provider '${providerName}' model at index ${index}: missing or invalid "id"`);
  }
  const defaults = {
    name: m.id,
    reasoning: false,
    input: ["text"] as ("text" | "image")[],
    contextWindow: 32768,
    maxTokens: 4096,
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
  };
  return { ...defaults, ...m };
}

function readIfPresent(path: string): { kind: "ok"; data: ModelsFile } | { kind: "missing" } | { kind: "invalid"; error: string } {
  if (!existsSync(path)) return { kind: "missing" };
  try {
    const raw = readFileSync(path, "utf-8");
    return { kind: "ok", data: parseModelsFile(raw) };
  } catch (err) {
    return { kind: "invalid", error: err instanceof Error ? err.message : String(err) };
  }
}

export function applyEnvOverrides(providers: Record<string, ProviderEntry>, env: NodeJS.ProcessEnv = process.env): Record<string, ProviderEntry> {
  const out: Record<string, ProviderEntry> = {};
  for (const [name, entry] of Object.entries(providers)) {
    const envVar = LEGACY_BASE_URL_ENV[name];
    if (envVar && env[envVar]) {
      out[name] = { ...entry, baseUrl: env[envVar]! };
    } else {
      out[name] = entry;
    }
  }
  return out;
}

/**
 * Merge: user file's providers fully replace package providers with the same
 * key. Providers only in the user file are added. Providers only in the
 * package default are kept. (We deliberately avoid deep per-model merging —
 * the user redeclares the whole provider entry if they want to change it,
 * which is far less surprising than "your override silently inherited fields
 * from a future package release.")
 */
export function mergeProviders(
  pkgDefault: Record<string, ProviderEntry>,
  userOverride: Record<string, ProviderEntry> | undefined,
): Record<string, ProviderEntry> {
  if (!userOverride) return { ...pkgDefault };
  return { ...pkgDefault, ...userOverride };
}

/**
 * Load the package default models.json + (optionally) the user override file,
 * apply env-var baseUrl overrides for the legacy providers, and return the
 * merged provider map plus diagnostics for each source.
 */
export function loadProviders(pkgRoot: string, env: NodeJS.ProcessEnv = process.env): LoadResult {
  const sources: LoadResult["sources"] = [];
  const defaultPath = join(pkgRoot, "models.json");
  const defaultRead = readIfPresent(defaultPath);
  let pkgDefault: Record<string, ProviderEntry> = {};
  if (defaultRead.kind === "ok") {
    pkgDefault = defaultRead.data.providers;
    sources.push({ path: defaultPath, status: "ok" });
  } else if (defaultRead.kind === "missing") {
    sources.push({ path: defaultPath, status: "missing" });
  } else {
    sources.push({ path: defaultPath, status: "invalid", error: defaultRead.error });
  }

  const overridePath = resolveOverridePath(env);
  let userOverride: Record<string, ProviderEntry> | undefined;
  if (overridePath) {
    const userRead = readIfPresent(overridePath);
    if (userRead.kind === "ok") {
      userOverride = userRead.data.providers;
      sources.push({ path: overridePath, status: "ok" });
    } else if (userRead.kind === "missing") {
      sources.push({ path: overridePath, status: "missing" });
    } else {
      sources.push({ path: overridePath, status: "invalid", error: userRead.error });
    }
  }

  const merged = mergeProviders(pkgDefault, userOverride);
  const withEnv = applyEnvOverrides(merged, env);
  return { providers: withEnv, sources };
}

// ── live context-window detection (llama.cpp /props) ────────────────────────
// little-coder budgets against the model's registered contextWindow. Rather than
// trust the static value in models.json, we ask a running llama.cpp server for
// its actual n_ctx at startup, so a `-c 131072` server shows 128k instead of the
// declared default. Best-effort: any failure falls back to the declared window.

/** Derive the llama.cpp `/props` URL from an OpenAI-style baseUrl. llama-server
 *  serves /props at the server ROOT, not under /v1 (which 404s), so strip a
 *  trailing /v1 (and any trailing slash) before appending /props. */
export function propsUrlFor(baseUrl: string): string {
  const root = baseUrl.replace(/\/+$/, "").replace(/\/v1$/, "");
  return `${root}/props`;
}

/** Pull the context window (n_ctx) out of a llama.cpp /props response. It lives
 *  at default_generation_settings.n_ctx (the per-slot window — exactly what one
 *  conversation can use); some builds also expose a top-level n_ctx. Returns
 *  undefined when absent or not a positive number. */
export function contextWindowFromProps(json: unknown): number | undefined {
  const j = json as { default_generation_settings?: { n_ctx?: unknown }; n_ctx?: unknown } | null;
  const n = Number(j?.default_generation_settings?.n_ctx ?? j?.n_ctx);
  return Number.isFinite(n) && n > 0 ? n : undefined;
}

export interface ProbeDeps {
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
  url?: string;
}

/** Ask a llama.cpp server for its live context window via /props. Returns
 *  undefined on ANY failure (server down, no /props, non-JSON, timeout) so the
 *  caller falls back to the declared window — never throws, never blocks beyond
 *  timeoutMs. */
export async function probeContextWindow(baseUrl: string, deps: ProbeDeps = {}): Promise<number | undefined> {
  const fetchImpl = deps.fetchImpl ?? fetch;
  const url = deps.url ?? propsUrlFor(baseUrl);
  const timeoutMs = deps.timeoutMs ?? 1500;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetchImpl(url, { signal: ctrl.signal });
    if (!res.ok) return undefined;
    return contextWindowFromProps(await res.json());
  } catch {
    return undefined;
  } finally {
    clearTimeout(timer);
  }
}
