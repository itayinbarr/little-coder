import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import {
  formatContextWindow,
  loadProviders,
  probeContextWindow,
  windowChange,
  withContextWindow,
  type ProviderModelEntry,
} from "./config.ts";

// Data-driven provider registration. Reads:
//   1. <pkgRoot>/models.json                       (shipped default)
//   2. $LITTLE_CODER_MODELS_FILE (if set), else
//      $XDG_CONFIG_HOME/little-coder/models.json, else
//      $HOME/.config/little-coder/models.json     (user override; per-provider replace)
//   3. LLAMACPP_BASE_URL / OLLAMA_BASE_URL env    (per-provider baseUrl override)
//
// Issue #13: previously the model list was hardcoded here and models.json was
// only documentation, which made any user edit a no-op until they forked.

const here = dirname(fileURLToPath(import.meta.url));
const pkgRoot = resolve(here, "..", "..", "..");

export default async function (pi: ExtensionAPI) {
  const result = loadProviders(pkgRoot);

  for (const src of result.sources) {
    if (src.status === "invalid") {
      console.error(`[llama-cpp-provider] ignoring ${src.path}: ${src.error}`);
    }
  }

  const providerCount = Object.keys(result.providers).length;
  if (providerCount === 0) {
    console.error(
      `[llama-cpp-provider] no providers loaded — checked: ${result.sources.map((s) => `${s.path} [${s.status}]`).join(", ")}`,
    );
    return;
  }

  // Opt-out for offline / CI / no-server launches that don't want a startup probe.
  const probeDisabled = process.env.LITTLE_CODER_NO_CTX_PROBE === "1";
  const probeOpts = () => ({
    url: process.env.LITTLE_CODER_LLAMACPP_PROPS_URL || undefined,
    timeoutMs: Number(process.env.LITTLE_CODER_CTX_PROBE_TIMEOUT_MS) || undefined,
  });

  // Captured so the model_select hook below can re-register llamacpp with a new
  // window after a llama-swap swap (see issue #54).
  let llamacpp:
    | { baseUrl: string; apiKey: string; api: string; models: ProviderModelEntry[]; registeredCtx?: number }
    | undefined;

  for (const [name, entry] of Object.entries(result.providers)) {
    let models = entry.models;

    // Auto-detect the server's live context window so the model registers with
    // the real n_ctx (e.g. a `-c 131072` server) instead of models.json's
    // declared default — the TUI readout, read-guard, and context budget all
    // follow the registered window. llama.cpp-only (the /props endpoint); any
    // failure silently keeps the declared window, so this never breaks startup.
    if (!probeDisabled && name === "llamacpp" && entry.models.length > 0) {
      const probed = await probeContextWindow(entry.baseUrl, probeOpts());
      if (probed) {
        models = withContextWindow(entry.models, probed);
      }
    }

    // pi's ProviderModelConfig.input is typed ("text"|"image")[], but the
    // registerProvider path stores model entries verbatim (see config.ts), so
    // we cast through to forward the full modality list (e.g. "video") to the
    // registry for providers whose current catalog advertises it.
    pi.registerProvider(name, {
      baseUrl: entry.baseUrl,
      apiKey: entry.apiKey,
      api: entry.api,
      models: models as unknown as Parameters<typeof pi.registerProvider>[1]["models"],
    });

    if (name === "llamacpp") {
      llamacpp = {
        baseUrl: entry.baseUrl,
        apiKey: entry.apiKey,
        api: entry.api,
        models,
        registeredCtx: models[0]?.contextWindow,
      };
    }
  }

  // Issue #54: llama-swap can swap the loaded model under a single endpoint,
  // which changes the server's live n_ctx. The startup probe only runs once, so
  // after a swap little-coder kept reporting the OLD window — and that drives
  // real behavior (read-guard + context-budget math), not just the readout.
  //
  // Re-probe /props whenever the active model changes TO a llamacpp model and
  // re-register the provider with the fresh window, with a one-line notice so a
  // drop like 128k → 16k never silently mis-sizes the budget mid-task. We skip
  // the initial selection (previousModel undefined — startup already probed) and
  // honor the same LITTLE_CODER_NO_CTX_PROBE opt-out.
  if (!probeDisabled && llamacpp) {
    pi.on("model_select", async (event, ctx) => {
      const lc = llamacpp!;
      const model = (event as any).model;
      const previous = (event as any).previousModel;
      if (!model || model.provider !== "llamacpp" || !previous) return;

      const probed = await probeContextWindow(lc.baseUrl, probeOpts());
      const change = windowChange(lc.registeredCtx, probed);
      if (!change) return;

      lc.models = withContextWindow(lc.models, change.to);
      lc.registeredCtx = change.to;
      pi.registerProvider("llamacpp", {
        baseUrl: lc.baseUrl,
        apiKey: lc.apiKey,
        api: lc.api,
        models: lc.models as unknown as Parameters<typeof pi.registerProvider>[1]["models"],
      });

      const from = change.from !== undefined ? formatContextWindow(change.from) : "?";
      ctx?.ui?.notify?.(`context window updated ${from} → ${formatContextWindow(change.to)}`, "info");
    });
  }
}
