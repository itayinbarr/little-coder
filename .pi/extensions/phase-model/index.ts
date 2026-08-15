import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { resolveOverridePath } from "../llama-cpp-provider/config.ts";
import { terminalColumns, truncateLineToWidth } from "../_shared/width.ts";
import {
  formatModelRef,
  matchesPrefix,
  modelForPhase,
  parseModelRef,
  phaseSummary,
  resolvePhaseDefaults,
  shouldSwitch,
  type Handover,
  type Phase,
  type PhaseDefaults,
} from "./phases.ts";

// Per-phase model selection (issue #61): run planning on one model and
// implementation on another, without retyping ctrl+P at every transition.
//
// This extension owns the two tags and the handover policy. It does NOT decide
// when a phase begins — plan-mode does, by calling enterPhase() at the two
// moments that matter (starting a plan, approving one). Keeping the policy here
// and the triggers there means deep-research (which has the same plan/act shape)
// can adopt it later by calling the same function.
//
// See phases.ts for the reasoning behind two knobs, live-switchable state, and
// a user-chosen handover mode.

const INDICATOR_KEY = "phase-model";
const gray = (s: string) => `\x1b[90m${s}\x1b[39m`;
const honey = (s: string) => `\x1b[38;2;225;90;31m${s}\x1b[39m`;

interface State {
  planModel?: string;
  actionModel?: string;
  handover: Handover;
}

// The phase tags live on globalThis, NOT in a module-level binding.
//
// pi loads every bundled extension with its own `--extension <path>`, and
// plan-mode additionally imports this file to call enterPhase(). Those two
// paths do not reliably resolve to the same module instance, so a module-level
// `state` gives the command handlers one copy and plan-mode a different, empty
// one — `/plan-model` appears to work (the indicator updates) while Plan Mode
// silently keeps running on the active model, with no error to explain it.
// Found exactly that way: the footer said "plan qwen3.6-27b" and the status
// line never moved off the 35B.
//
// A process-wide key is the one thing both instances certainly agree on.
const STATE_KEY = "__littleCoderPhaseModel";

function sharedState(): State & { loaded: boolean } {
  const g = globalThis as any;
  if (!g[STATE_KEY]) g[STATE_KEY] = { handover: "auto", loaded: false };
  return g[STATE_KEY];
}

const state = sharedState();

// pi's `getArgumentCompletions(prefix)` gets no ctx, so the selectable set is
// cached here from the events that do have one. Empty until the first
// session_start, which is fine: completion falls back to null (no suggestions)
// and typing a full provider/id still works.
let cachedRefs: string[] = [];

function setPhaseModel(phase: Phase, ref: string | undefined): void {
  if (phase === "plan") state.planModel = ref;
  else state.actionModel = ref;
}

function getPhaseModel(phase: Phase): string | undefined {
  return phase === "plan" ? state.planModel : state.actionModel;
}

function readJsonSafe(path: string | undefined): any {
  if (!path || !existsSync(path)) return undefined;
  try {
    return JSON.parse(readFileSync(path, "utf-8"));
  } catch {
    return undefined;
  }
}

/** Repo/package root — this file lives at .pi/extensions/phase-model/. */
function pkgRoot(): string {
  return join(dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
}

function loadDefaults(): PhaseDefaults {
  const shipped = readJsonSafe(join(pkgRoot(), "models.json"));
  const user = readJsonSafe(resolveOverridePath());
  return resolvePhaseDefaults(shipped, user);
}

/** Reset to configured defaults. Called at session start so a /clear or a
 *  resumed session starts from config rather than inheriting stale tags. */
export function resetState(): void {
  const d = loadDefaults();
  state.planModel = d.planModel;
  state.actionModel = d.actionModel;
  state.handover = d.handover;
  state.loaded = true;
}

function ensureLoaded(): void {
  if (!state.loaded) resetState();
}

/** "provider/id" of the session's active model. */
function activeRef(ctx: any): string | undefined {
  const m = ctx?.model;
  if (!m || typeof m.id !== "string") return undefined;
  return m.provider ? `${m.provider}/${m.id}` : m.id;
}

/** Every model this session may select, as "provider/id". Prefers
 *  ctx.scopedModels (mirrors pi's own ctrl+P set) and falls back to the full
 *  catalogue when no scoping is configured. Also refreshes the completion
 *  cache, since this is the only place with a ctx to read it from. */
function refreshRefs(ctx: any): string[] {
  const refs = selectableRefs(ctx);
  if (refs.length > 0) cachedRefs = refs;
  return refs;
}

function selectableRefs(ctx: any): string[] {
  const scoped = ctx?.scopedModels;
  if (Array.isArray(scoped) && scoped.length > 0) {
    return scoped
      .map((e: any) => e?.model)
      .filter((m: any) => m && typeof m.id === "string")
      .map((m: any) => (m.provider ? `${m.provider}/${m.id}` : m.id));
  }
  const all = ctx?.modelRegistry?.getAvailable?.() ?? [];
  return all
    .filter((m: any) => m && typeof m.id === "string")
    .map((m: any) => (m.provider ? `${m.provider}/${m.id}` : m.id));
}

/** The model ref a given phase should run on right now. Exported so plan-mode
 *  can pick the right model for its sub-coders without switching the session. */
export function phaseModel(ctx: any, phase: Phase): string | undefined {
  ensureLoaded();
  return modelForPhase(phase, state, activeRef(ctx));
}

/**
 * Switch the session's active model for `phase`, if policy says to.
 *
 * Returns a short human sentence describing what happened (or why nothing did),
 * which the caller surfaces via notify. Never throws: a failed model switch must
 * degrade to "carry on with the current model", not abort a plan the user has
 * been waiting minutes for.
 */
export async function enterPhase(pi: ExtensionAPI, ctx: any, phase: Phase): Promise<string | undefined> {
  ensureLoaded();
  const decision = shouldSwitch(phase, state, activeRef(ctx));
  if (!decision.switch) return undefined;

  const ref = parseModelRef(decision.to);
  if (!ref) return undefined;
  try {
    const model = ctx?.modelRegistry?.find?.(ref.provider, ref.id);
    if (!model) return `${phase} model ${decision.to} is not available — staying on the current model`;
    const ok = await pi.setModel(model);
    if (!ok) return `no API key for ${decision.to} — staying on the current model`;
    setIndicator(ctx);
    return `${phase} model: ${decision.to}`;
  } catch (e) {
    return `could not switch to ${decision.to}: ${(e as Error)?.message ?? e}`;
  }
}

function indicatorLines(): string[] | undefined {
  const summary = phaseSummary(state);
  if (!summary) return undefined;
  const raw = `${honey("◇")} ${gray(summary)}`;
  return [truncateLineToWidth(raw, terminalColumns())];
}

function setIndicator(ctx: any): void {
  if (!ctx?.hasUI) return;
  try {
    ctx.ui.setWidget(INDICATOR_KEY, indicatorLines(), { placement: "belowEditor" });
  } catch {
    /* widget surface unavailable in some run modes */
  }
}

/** Shared implementation of /plan-model and /action-model. */
function registerPhaseCommand(pi: ExtensionAPI, phase: Phase): void {
  const cmd = phase === "plan" ? "plan-model" : "action-model";
  pi.registerCommand(cmd, {
    description:
      phase === "plan"
        ? "Set the model used for planning (no arg: show it; 'off': untag)"
        : "Set the model used for implementation (no arg: show it; 'off': untag)",
    getArgumentCompletions: (prefix: string) => {
      const items = cachedRefs
        .filter((r) => matchesPrefix(r, prefix))
        .map((r) => ({ value: r, label: r }));
      return items.length > 0 ? items : null;
    },
    handler: async (args: string, ctx: any) => {
      ensureLoaded();
      const arg = String(args ?? "").trim();

      if (!arg) {
        const cur = getPhaseModel(phase);
        ctx.ui?.notify?.(
          cur ? `${phase} model: ${cur}` : `${phase} model: not set (uses the active model)`,
          "info",
        );
        return;
      }

      if (arg === "off" || arg === "none") {
        setPhaseModel(phase, undefined);
        setIndicator(ctx);
        ctx.ui?.notify?.(`${phase} model cleared — falls back to the active model`, "info");
        return;
      }

      // Accept an exact provider/id, or a unique fuzzy match over the
      // selectable set so `/plan-model 35b` works the way the picker does.
      const refs = refreshRefs(ctx);
      let chosen = refs.find((r) => r === arg);
      if (!chosen) {
        const hits = refs.filter((r) => matchesPrefix(r, arg));
        if (hits.length === 1) chosen = hits[0];
        else if (hits.length > 1) {
          ctx.ui?.notify?.(`"${arg}" matches ${hits.length} models: ${hits.slice(0, 4).join(", ")}…`, "warning");
          return;
        }
      }
      if (!chosen) {
        // Not in the catalogue, but a well-formed ref is still worth honoring —
        // a provider can appear later in the session (issue #54's re-probe).
        const parsed = parseModelRef(arg);
        if (!parsed) {
          ctx.ui?.notify?.(`"${arg}" is not a known model or a provider/id ref`, "error");
          return;
        }
        chosen = formatModelRef(parsed);
      }

      setPhaseModel(phase, chosen);
      setIndicator(ctx);
      ctx.ui?.notify?.(`${phase} model: ${chosen}`, "info");
    },
  });
}

export default function (pi: ExtensionAPI) {
  registerPhaseCommand(pi, "plan");
  registerPhaseCommand(pi, "action");

  pi.registerCommand("model-handover", {
    description: "Switch models automatically between phases, or leave it to you (auto|manual)",
    getArgumentCompletions: (prefix: string) => {
      const items = ["auto", "manual"]
        .filter((v) => v.startsWith(prefix.toLowerCase()))
        .map((v) => ({ value: v, label: v }));
      return items.length > 0 ? items : null;
    },
    handler: async (args: string, ctx: any) => {
      ensureLoaded();
      const arg = String(args ?? "").trim().toLowerCase();
      if (!arg) {
        ctx.ui?.notify?.(`model handover: ${state.handover}`, "info");
        return;
      }
      if (arg !== "auto" && arg !== "manual") {
        ctx.ui?.notify?.(`handover must be "auto" or "manual"`, "error");
        return;
      }
      state.handover = arg;
      setIndicator(ctx);
      ctx.ui?.notify?.(
        arg === "auto"
          ? "model handover: auto — approving a plan switches to the action model"
          : "model handover: manual — little-coder will not switch models for you",
        "info",
      );
    },
  });

  pi.registerCommand("phase-models", {
    description: "Show the plan/action model tags and handover mode",
    handler: async (_args: string, ctx: any) => {
      ensureLoaded();
      const active = activeRef(ctx) ?? "(none)";
      const lines = [
        `active:  ${active}`,
        `plan:    ${state.planModel ?? "(unset — uses active)"}`,
        `action:  ${state.actionModel ?? "(unset — uses active)"}`,
        `handover: ${state.handover}`,
      ];
      ctx.ui?.notify?.(lines.join("\n"), "info");
    },
  });

  // Re-render the indicator when the user changes models by other means
  // (ctrl+P, /model), so the footer never disagrees with reality.
  pi.on("model_select", async (_event, ctx) => {
    refreshRefs(ctx);
    setIndicator(ctx);
  });

  pi.on("session_start", async (_event, ctx) => {
    resetState();
    refreshRefs(ctx);
    setIndicator(ctx);
  });
}
