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

/** Re-stamp every model with a new context window (keeps all other fields). */
export function withContextWindow(
  models: ProviderModelEntry[],
  contextWindow: number,
): ProviderModelEntry[] {
  return models.map((m) => ({ ...m, contextWindow }));
}

/** Human "Nk" label for a context window. llama.cpp n_ctx values are ×1024
 *  multiples, so dividing by 1024 yields the clean numbers users expect
 *  (131072 → "128k", 32768 → "32k"). */
export function formatContextWindow(n: number): string {
  return `${Math.round(n / 1024)}k`;
}

/** Decide whether a freshly probed window warrants a re-register + notice.
 *  Returns the `{ from, to }` transition, or null when nothing should change —
 *  the probe failed (undefined) or it matches the already-registered window.
 *  Pure so the swap-time logic is unit-testable without a pi runtime. */
export function windowChange(
  registeredCtx: number | undefined,
  probed: number | undefined,
): { from: number | undefined; to: number } | null {
  if (!probed || probed === registeredCtx) return null;
  return { from: registeredCtx, to: probed };
}

/** models.json stores apiKey as an ENV_VAR_NAME (see schema above); a value
 *  that names no env var is treated as a literal key (llama-swap setups often
 *  paste the raw key). Returns undefined when nothing usable is set. */
export function resolveApiKey(configured: string | undefined, env: NodeJS.ProcessEnv = process.env): string | undefined {
  if (!configured) return undefined;
  return env[configured] ?? configured;
}

export interface ProbeDeps {
  fetchImpl?: typeof fetch;
  timeoutMs?: number;
  url?: string;
  /** Sent as a Bearer token — /props sits behind the server's --api-key
   *  middleware (llama.cpp and llama-swap), so an unauthenticated probe
   *  gets 401 {"error":{"message":"Invalid API Key",...}} and the caller
   *  silently falls back to the declared context window. */
  apiKey?: string;
}

/** Ask a llama.cpp server for its live context window via /props. Returns
 *  undefined on ANY failure (server down, no /props, non-JSON, timeout) so the
 *  caller falls back to the declared window — never throws, never blocks beyond
 *  timeoutMs. */
export async function probeContextWindow(baseUrl: string, deps: ProbeDeps = {}): Promise<number | undefined> {
  const fetchImpl = deps.fetchImpl ?? fetch;
  const url = deps.url ?? propsUrlFor(baseUrl);
  const timeoutMs = deps.timeoutMs ?? 1500;
  const headers: Record<string, string> = {};
  if (deps.apiKey) headers.Authorization = `Bearer ${deps.apiKey}`;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    const res = await fetchImpl(url, { signal: ctrl.signal, headers });
    if (!res.ok) return undefined;
    return contextWindowFromProps(await res.json());
  } catch {
    return undefined;
  } finally {
    clearTimeout(timer);
  }
}

/** Router-mode fallback. llama-swap answers root /props itself ("role":"router",
 *  default_generation_settings.n_ctx = 0), so the /props probe finds nothing.
 *  Its /v1/models listing DOES carry per-model data: meta.n_ctx once the model
 *  is loaded, otherwise --ctx-size in the recorded launch args. Returns
 *  undefined when nothing usable is found. */
export function contextWindowFromModelList(json: unknown, modelId?: string): number | undefined {
  const j = json as { data?: any[] } | null;
  const models = Array.isArray(j?.data) ? j.data : [];
  const pick =
    (modelId ? models.find((m) => m && m.id === modelId) : undefined) ??
    (models.length === 1 ? models[0] : undefined);
  if (!pick) return undefined;
  const metaN = Number(pick.meta?.n_ctx);
  if (Number.isFinite(metaN) && metaN > 0) return metaN;
  const args: string[] = Array.isArray(pick.status?.args) ? pick.status.args : [];
  const i = args.indexOf("--ctx-size");
  const fromArgs = i >= 0 ? Number(args[i + 1]) : NaN;
  return Number.isFinite(fromArgs) && fromArgs > 0 ? fromArgs : undefined;
}

/** Probe the router's /v1/models for the live context window of one model.
 *  The key is sent even though llama.cpp leaves this endpoint open — a
 *  self-hosted reverse proxy in front may still require it.
 *  Same best-effort contract as probeContextWindow: never throws. */
export async function probeContextWindowViaModels(
  baseUrl: string,
  deps: ProbeDeps & { modelId?: string } = {},
): Promise<number | undefined> {
  const fetchImpl = deps.fetchImpl ?? fetch;
  const root = baseUrl.replace(/\/+$/, "").replace(/\/v1$/, "");
  const headers: Record<string, string> = {};
  if (deps.apiKey) headers.Authorization = `Bearer ${deps.apiKey}`;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), deps.timeoutMs ?? 1500);
  try {
    const res = await fetchImpl(`${root}/v1/models`, { signal: ctrl.signal, headers });
    if (!res.ok) return undefined;
    return contextWindowFromModelList(await res.json(), deps.modelId);
  } catch {
    return undefined;
  } finally {
    clearTimeout(timer);
  }
}

/** Every model a router-mode endpoint actually serves, as registry entries.
 *
 *  models.json is a curated list of models little-coder knows how to talk to.
 *  Behind a router (llama-swap, `llama-server --models-preset`) the endpoint
 *  serves whatever presets the user configured, and those ids are not in
 *  models.json, so `--list-models` never showed them and selecting one failed
 *  with "model not found" (issue #112, @NoelJacob: 13 presets on the server,
 *  none of them listed).
 *
 *  Deliberately returns nothing for a SINGLE-model listing. That is the
 *  ordinary local case, where models.json's friendly alias (`qwen3.6-35b-a3b`)
 *  is the name the user wants, and adding the raw served id next to it
 *  (`Qwen3.6-35B-A3B-UD-Q4_K_M.gguf`) would be duplicate noise for everyone.
 *  More than one model IS a router, which is exactly the case this exists for.
 *
 *  `declared` ids are never shadowed: discovery only ADDS. */
export function discoveredModels(
  json: unknown,
  declared: ReadonlyArray<{ id: string }>,
  fallbackWindow: number,
): ProviderModelEntry[] {
  const j = json as { data?: any[] } | null;
  const models = Array.isArray(j?.data) ? j.data : [];
  if (models.length < 2) return [];
  const known = new Set(declared.map((m) => m.id));
  const out: ProviderModelEntry[] = [];
  for (const m of models) {
    const id = typeof m?.id === "string" ? m.id : "";
    if (!id || known.has(id)) continue;
    known.add(id);
    // Reuse the same defaults a models.json entry gets, so a discovered model
    // is shaped exactly like a declared one.
    out.push(
      fillModelDefaults(
        { id, contextWindow: contextWindowFromModelList({ data: [m] }, id) ?? fallbackWindow },
        "llamacpp",
        out.length,
      ),
    );
  }
  return out;
}

/** Fetch <root>/v1/models and turn it into registry entries. Best-effort. */
export async function probeServedModels(
  baseUrl: string,
  declared: ReadonlyArray<{ id: string }>,
  fallbackWindow: number,
  deps: ProbeDeps = {},
): Promise<ProviderModelEntry[]> {
  const fetchImpl = deps.fetchImpl ?? fetch;
  const root = baseUrl.replace(/\/+$/, "").replace(/\/v1$/, "");
  const headers: Record<string, string> = {};
  if (deps.apiKey) headers.Authorization = `Bearer ${deps.apiKey}`;
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), deps.timeoutMs ?? 1500);
  try {
    const res = await fetchImpl(`${root}/v1/models`, { signal: ctrl.signal, headers });
    if (!res.ok) return [];
    return discoveredModels(await res.json(), declared, fallbackWindow);
  } catch {
    return [];
  } finally {
    clearTimeout(timer);
  }
}

/** Try /props first (direct llama.cpp), then /v1/models (router mode). */
export async function probeContextWindowAuto(
  baseUrl: string,
  deps: ProbeDeps & { modelId?: string } = {},
): Promise<number | undefined> {
  return (await probeContextWindow(baseUrl, deps)) ?? (await probeContextWindowViaModels(baseUrl, deps));
}
