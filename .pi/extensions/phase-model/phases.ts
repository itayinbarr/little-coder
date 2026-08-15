// Pure logic for per-phase model selection (issue #61). No pi runtime, no disk
// access beyond what the caller hands in, so all of it is unit-testable.
//
// The shape settled in the #61 thread: TWO knobs, a plan model and an action
// model, not one per sub-phase. @cndjonno's walkthrough is what pinned the rest
// of the design down — they swap the plan model *mid-session* to A/B two
// planners against the same brief, which means the knobs cannot be static
// config read once at launch. So: models.json supplies the DEFAULTS, and which
// model is currently "plan" and which is "action" is session state that
// `/plan-model` and `/action-model` mutate live.
//
// Handover is deliberately a user choice rather than a hardcoded behavior
// ("don't make the choice for them" — @cndjonno):
//   auto   — approving a plan switches the session to the action model for you.
//   manual — the tags exist and are shown, but little-coder never switches the
//            active model on your behalf; you drive it with ctrl+P or the
//            commands. Costs nothing, surprises no one.
//
// Why the toggle matters more here than it would on a hosted provider: on a
// single local llama.cpp box, switching models evicts and reloads weights. An
// automatic handover can silently trigger a 15+ second stall mid-thought, so
// "never switch for me" is a legitimate performance preference, not just taste.

export type Handover = "auto" | "manual";
export type Phase = "plan" | "action";

export interface ModelRef {
  provider: string;
  id: string;
}

export interface PhaseDefaults {
  planModel?: string;
  actionModel?: string;
  handover: Handover;
}

/** Split a "provider/id" model ref. Null unless both halves are non-empty and
 *  separated by a single leading "/" (a bare id is not a valid ref here —
 *  little-coder always addresses models as provider/id). */
export function parseModelRef(ref: unknown): ModelRef | null {
  if (typeof ref !== "string") return null;
  const slash = ref.indexOf("/");
  if (slash <= 0 || slash === ref.length - 1) return null;
  const provider = ref.slice(0, slash);
  const id = ref.slice(slash + 1);
  if (!provider || !id || id.includes("/")) return null;
  return { provider, id };
}

export function formatModelRef(r: ModelRef): string {
  return `${r.provider}/${r.id}`;
}

function validHandover(v: unknown): Handover | undefined {
  return v === "auto" || v === "manual" ? v : undefined;
}

function validRef(v: unknown): string | undefined {
  return parseModelRef(v) ? (v as string) : undefined;
}

/**
 * Resolve the configured defaults. Precedence, highest first:
 *   1. environment (LITTLE_CODER_PLAN_MODEL / _ACTION_MODEL / _MODEL_HANDOVER)
 *   2. the user's models.json override
 *   3. the shipped models.json
 *
 * Same precedence the launcher already uses for the top-level `"default"`
 * (issue #65), so there is one rule to learn rather than two. An invalid value
 * at a higher level does not mask a valid one below it — a typo'd env var falls
 * through to the file rather than silently disabling the feature.
 */
export function resolvePhaseDefaults(
  shipped: any,
  user: any,
  env: NodeJS.ProcessEnv = process.env,
): PhaseDefaults {
  const pick = (key: string, envVar: string): string | undefined =>
    validRef(env[envVar]) ?? validRef(user?.[key]) ?? validRef(shipped?.[key]);

  const planModel = pick("planModel", "LITTLE_CODER_PLAN_MODEL");
  const actionModel = pick("actionModel", "LITTLE_CODER_ACTION_MODEL");

  const handover =
    validHandover(env.LITTLE_CODER_MODEL_HANDOVER) ??
    validHandover(user?.handover) ??
    validHandover(shipped?.handover) ??
    "auto";

  return { planModel, actionModel, handover };
}

/**
 * The model a phase should run on, given the session's tags and whatever is
 * active right now.
 *
 * The fallback chain is the whole ergonomic promise of the feature: if you
 * never configure anything, both phases resolve to the active model and
 * nothing about little-coder changes. If you set only one knob, the other
 * falls back to the active model rather than to the other knob — setting a big
 * planner must not silently drag your implementation onto it too.
 */
export function modelForPhase(
  phase: Phase,
  state: { planModel?: string; actionModel?: string },
  activeModel: string | undefined,
): string | undefined {
  const tagged = phase === "plan" ? state.planModel : state.actionModel;
  return tagged ?? activeModel;
}

/**
 * Should we actually call setModel to enter `phase`?
 *
 * False when nothing is tagged for the phase, when the target is already
 * active, or when handover is manual. The "already active" check is what keeps
 * a plan→action handover from evicting and reloading identical weights on a
 * single-backend local setup.
 */
export function shouldSwitch(
  phase: Phase,
  state: { planModel?: string; actionModel?: string; handover: Handover },
  activeModel: string | undefined,
): { switch: false; reason: string } | { switch: true; to: string } {
  if (state.handover === "manual") return { switch: false, reason: "handover is manual" };
  const target = phase === "plan" ? state.planModel : state.actionModel;
  if (!target) return { switch: false, reason: `no ${phase} model configured` };
  if (target === activeModel) return { switch: false, reason: "already active" };
  return { switch: true, to: target };
}

/** Fuzzy-ish match for command autocomplete: every whitespace-separated term in
 *  the prefix must appear somewhere in the candidate, case-insensitively. Lets
 *  `/plan-model 35b` and `/plan-model llama 35` both find llamacpp/qwen3.6-35b-a3b. */
export function matchesPrefix(candidate: string, prefix: string): boolean {
  const terms = prefix.toLowerCase().split(/\s+/).filter(Boolean);
  if (terms.length === 0) return true;
  const hay = candidate.toLowerCase();
  return terms.every((t) => hay.includes(t));
}

/** One-line summary for the footer indicator and `/phase-models`. Returns
 *  undefined when there is nothing worth showing — neither knob set — so an
 *  unconfigured session gets no extra chrome. */
export function phaseSummary(state: {
  planModel?: string;
  actionModel?: string;
  handover: Handover;
}): string | undefined {
  if (!state.planModel && !state.actionModel) return undefined;
  const short = (ref?: string) => (ref ? ref.split("/").slice(1).join("/") || ref : "active");
  return `plan ${short(state.planModel)} → act ${short(state.actionModel)}${
    state.handover === "manual" ? " (manual)" : ""
  }`;
}
