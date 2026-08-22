import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { injectionResult } from "../_shared/inject.ts";
import { terminalColumns, truncateLineToWidth } from "../_shared/width.ts";
import { enterPhase } from "../phase-model/index.ts";
import { currentModelId } from "../subagent/index.ts";
import {
  runSubCoder,
  runSubCodersConcurrent,
  truncateReport,
  type SubCoderItem,
  type SubCoderResult,
} from "../subagent/spawn.ts";
import { SubCoderTracker } from "../subagent/tracker.ts";
import { PlanStatus } from "./status.ts";

// Approved plans are persisted project-locally so they survive the planning
// session and can be picked up later by the user-initiated /implement command.
const APPROVED_PLAN_FILE = join(".pi", "approved-plan.md");

const APPROVE_CHOICE = "Approve plan";
const KEEP_PLANNING_CHOICE = "Keep planning (don't implement)";

// Plan Mode — a Claude-Code-style "research, ask, then plan" flow.
//
// ctrl+q toggles plan mode (an indicator appears below the input). While it is
// on, submitting a prompt does NOT run a normal coding turn; instead the
// extension orchestrates:
//   1. decompose the request into 1-4 exploration tasks (a reasoning sub-coder),
//   2. dispatch those as read-only explorer sub-coders (isolated context; only
//      their concise reports survive — their transcripts never enter this window),
//   3. generate 1-3 clarifying questions with suggested answers (a sub-coder),
//   4. ask them via the UI (with a free-text "Other" option),
//   5. synthesize the reports + answers into a written plan in the main window,
//   6. exit plan mode.
//
// An extension can't call inference directly, so every reasoning step is a
// child little-coder (spawned via ../subagent/spawn.ts), and the final plan is
// injected as a normal turn via pi.sendUserMessage so it lands in the chat.
//
// ctrl+q is unbound by pi AND by the emacs-style editor (which claims nearly
// every other ctrl+<letter> — ctrl+y is its yank/paste, ctrl+a/e line motion,
// etc.), so the extension can claim it cleanly without a conflict warning or
// shadowing a built-in (shift+tab stays pi's thinking-level cycle — issue #47).
// pi runs the terminal in raw mode (flow control off), so ctrl+q arrives as a
// clean \x11 byte on every terminal — unlike alt+p, which many terminals deliver
// as a literal "π" rather than ESC+p, so the original binding never fired.

const honey = (s: string) => `\x1b[38;2;225;90;31m${s}\x1b[39m`;
const gray = (s: string) => `\x1b[90m${s}\x1b[39m`;
const INDICATOR_KEY = "plan-mode";

let planModeOn = false;
let orchestrating = false;

// True only while the synthesis turn runs — blocks edits/writes so plan mode
// produces a plan, not changes.
let planGuardActive = false;

let currentAbort: AbortController | null = null;

// Set just before the synthesis turn; consumed by before_agent_start to inject
// the planning instructions + research into the system prompt (kept out of the
// visible chat). Null at all other times.
let pendingSynthesis: { digest: string; answers: string } | null = null;

// True while the plan-writing turn is in flight; on its agent_end we prompt the
// user to approve the generated plan.
let synthesisActive = false;

function indicatorLines(): string[] {
  // Cap to terminal width — pi-tui throws on overflow (issue #48). The
  // indicator is short, but truncate for defense in depth so even a narrow
  // terminal (≤ 30 cols) doesn't crash on widget render.
  const raw = `${honey("◆")} ${honey("PLAN MODE")}  ${gray("(ctrl-q to exit)")}`;
  return [truncateLineToWidth(raw, terminalColumns())];
}

function setIndicator(ctx: any, on: boolean): void {
  if (!ctx?.hasUI) return;
  ctx.ui.setWidget(INDICATOR_KEY, on ? indicatorLines() : undefined, {
    placement: "belowEditor",
  });
}

// Whether the session should open already in plan mode (issue #84). Set by the
// launcher when `--plan-mode` (or LITTLE_CODER_PLAN_MODE=1) is passed. Honored
// for interactive sessions only — never a headless `--mode`/`-p` run or a
// read-only sub-coder, which inherit the parent's env but must not plan.
export function wantsPlanModeAtStart(): boolean {
  if (process.env.LITTLE_CODER_PLAN_MODE !== "1") return false;
  if (process.env.LITTLE_CODER_SUBAGENT === "1") return false;

  const argv = process.argv;
  return !argv.includes("--mode") && !argv.includes("-p");
}

// Pull the first balanced JSON array out of a model reply (small models love to
// wrap JSON in prose / fences). Returns [] on failure so callers can fall back.
export function extractJsonArray(text: string): any[] {
  const start = text.indexOf("[");
  const end = text.lastIndexOf("]");

  if (start < 0 || end <= start) return [];

  try {
    const v = JSON.parse(text.slice(start, end + 1));
    return Array.isArray(v) ? v : [];
  } catch {
    return [];
  }
}

async function reason(
  task: string,
  cwd: string,
  model: string | undefined,
  signal: AbortSignal,
): Promise<string> {
  const r = await runSubCoder({
    id: "r",
    label: "planner",
    task,
    cwd,
    model,
    signal,
  });

  return r.report;
}

interface ExploreTask {
  label: string;
  task: string;
}

async function decomposeTargets(
  prompt: string,
  cwd: string,
  model: string | undefined,
  signal: AbortSignal,
): Promise<ExploreTask[]> {
  const text = await reason(
    `You are PLANNING, not executing — do not write or change anything. Given this user request, ` +
      `list the 1-4 most useful independent areas to investigate before an implementation plan can be written. ` +
      `Output ONLY a JSON array of objects {"label": "<3-4 word name>", "task": "<a specific research instruction ` +
      `for an agent that can read this repo and browse online>"}. No prose.\n\nUser request:\n${prompt}`,
    cwd,
    model,
    signal,
  );

  const parsed = extractJsonArray(text)
    .filter((t) => t && typeof t.task === "string")
    .slice(0, 4)
    .map((t, i) => ({
      label: String(t.label || `area ${i + 1}`).slice(0, 24),
      task: String(t.task),
    }));

  if (parsed.length > 0) return parsed;

  // Fallback: a single broad exploration of the request itself.
  return [
    {
      label: "explore",
      task: `Investigate this repository to inform: ${prompt}`,
    },
  ];
}

interface Question {
  q: string;
  options: string[];
}

async function generateQuestions(
  prompt: string,
  digest: string,
  cwd: string,
  model: string | undefined,
  signal: AbortSignal,
): Promise<Question[]> {
  const text = await reason(
    `Based on the user's request and the research findings below, propose 1-3 clarifying questions whose ` +
      `answers would change the implementation plan. For each, give 1-3 short suggested answers. Output ONLY a ` +
      `JSON array of {"q": "<question>", "options": ["<short answer>", ...]}. No prose.\n\n` +
      `User request:\n${prompt}\n\nResearch findings:\n${digest}`,
    cwd,
    model,
    signal,
  );

  return extractJsonArray(text)
    .filter((q) => q && typeof q.q === "string")
    .slice(0, 3)
    .map((q) => ({
      q: String(q.q),
      options: (Array.isArray(q.options) ? q.options : [])
        .map((o: any) => String(o))
        .filter(Boolean)
        .slice(0, 3),
    }));
}

export function digestReports(results: SubCoderResult[]): string {
  return results
    .map(
      (r) =>
        `### ${r.label}\n${
          r.exitCode === 0
            ? truncateReport(r.report)
            : `(failed: ${r.errorMessage || "no output"})`
        }`,
    )
    .join("\n\n");
}

// ---------------------------------------------------------------------------
// issue #98 — plan text extraction
// ---------------------------------------------------------------------------

/**
 * Extract the plan text from the most recent assistant message in a message list.
 *
 * Inspects only the latest assistant message. Concatenates all text parts in
 * order with "\n" separator and trims. Does NOT fall back to an older
 * assistant response if the latest has no usable text.
 */
export function extractPlanText(messages: unknown[]): string {
  for (let i = messages.length - 1; i >= 0; i--) {
    const msg = messages[i] as any;

    if (msg?.role !== "assistant") {
      continue;
    }

    if (Array.isArray(msg.content)) {
      const parts: string[] = [];

      for (const part of msg.content) {
        if (part?.type === "text" && typeof part.text === "string") {
          parts.push(part.text);
        }
      }

      return parts.join("\n").trim();
    }

    break;
  }

  return "";
}

// ---------------------------------------------------------------------------
// issue #98 — approved-plan persistence
// ---------------------------------------------------------------------------

interface PlanFs {
  writeFileSync(path: string, content: string, options?: any): void;
  mkdirSync(path: string, opts: { recursive: boolean }): void;
  readFileSync(path: string, options?: any): string;
}

type PlanNoticeType = "info" | "warning" | "error";

interface PlanUi {
  notify(msg: string, type?: PlanNoticeType): void;
}

interface PlanApprovalDeps {
  planText: string;
  approved: boolean;
  planFile: string;
  fs: PlanFs;
  ui: PlanUi;
}

/**
 * Persist an approved plan for later execution via /implement.
 *
 * Approval itself does not switch models, replace the session, or begin
 * implementation. pi exposes newSession() only to command handlers, so the
 * destructive transition remains explicitly user-initiated.
 */
export function handlePlanApproval(deps: PlanApprovalDeps): boolean {
  if (!deps.approved) {
    deps.ui.notify(
      "plan not approved — refine your request, or ctrl-q to start another plan",
      "info",
    );
    return false;
  }

  const planText = deps.planText.trim();

  if (!planText) {
    deps.ui.notify(
      "plan could not be captured — refine your request or ctrl-q to start another plan",
      "warning",
    );
    return false;
  }

  const planDir = dirname(deps.planFile);

  try {
    deps.fs.mkdirSync(planDir, { recursive: true });
    deps.fs.writeFileSync(deps.planFile, planText, "utf-8");
  } catch (err) {
    deps.ui.notify(
      `failed to save plan: ${(err as Error).message}`,
      "warning",
    );
    return false;
  }

  deps.ui.notify(
    `plan saved to ${deps.planFile} — run /implement when you are ready to execute it in a clean session`,
    "info",
  );

  return true;
}

// ---------------------------------------------------------------------------
// issue #98 — /implement command handler (extracted for testability)
// ---------------------------------------------------------------------------

interface ImplementDeps {
  cwd: string;
  planFile: string;
  ui: PlanUi;
  fs: PlanFs;
  pi: ExtensionAPI;
  ctx: any;
  enterPhase: (pi: ExtensionAPI, ctx: any, phase: "plan" | "action") => Promise<string | undefined>;
  newSession: (
    opts?: { setup?: (sm: any) => Promise<void>; withSession?: (ctx: any) => Promise<void> },
  ) => Promise<{ cancelled: boolean }>;
}

/**
 * Execute the approved plan in a fresh session.
 *
 * Reads the saved plan, switches to the action phase, replaces the session
 * (seeding it with the plan), and sends the implementation instruction.
 * Does not modify the persisted plan file.
 *
 * Ordering: read/validate plan → enter action phase → newSession → setup → withSession.
 */
export async function handleImplement(deps: ImplementDeps): Promise<void> {
  // Validate the saved plan before switching models or replacing anything.
  let approvedPlan: string;

  try {
    approvedPlan = deps.fs.readFileSync(deps.planFile, "utf-8").trim();
  } catch (err) {
    deps.ui.notify(
      `could not read approved plan at ${deps.planFile}: ${(err as Error).message}`,
      "warning",
    );
    return;
  }

  if (!approvedPlan) {
    deps.ui.notify(
      `approved plan at ${deps.planFile} is empty — create and approve a plan first`,
      "warning",
    );
    return;
  }

  // Phase-model handover happens when implementation actually begins,
  // rather than when the user merely approves the plan.
  const switched = await deps.enterPhase(deps.pi, deps.ctx, "action");

  if (switched) {
    deps.ui.notify(switched, "info");
  }

  let result: { cancelled: boolean };

  try {
    result = await deps.newSession({
      // Seed the new SessionManager before pi rebuilds the fresh agent
      // context. The hidden custom message participates in LLM context but
      // does not appear as another user-visible message.
      setup: async (sessionManager) => {
        sessionManager.appendCustomMessageEntry(
          "lc-approved-plan",
          `## Approved implementation plan\n\n${approvedPlan}`,
          false,
          {
            source: deps.planFile,
          },
        );
      },

      // This callback receives the replacement-session context. Never use the
      // old command ctx here.
      withSession: async (newCtx) => {
        await newCtx.sendUserMessage(
          "Implement the approved plan provided in this session context. Make the actual file changes now.",
        );
      },
    });
  } catch (err) {
    deps.ui.notify(
      `session replacement failed: ${(err as Error).message}`,
      "error",
    );
    return;
  }

  if (result.cancelled) {
    deps.ui.notify(
      `session replacement cancelled — approved plan remains at ${deps.planFile}`,
      "info",
    );
  }
}

const OTHER_SENTINEL = "✎ Other (type my own answer)";

async function askQuestions(
  ctx: any,
  questions: Question[],
): Promise<string> {
  const answered: string[] = [];

  for (const q of questions) {
    const options = [...q.options, OTHER_SENTINEL].filter(Boolean);

    let choice: string | undefined;

    try {
      choice = await ctx.ui.select(q.q, options);
    } catch {
      choice = undefined;
    }

    if (choice === undefined) {
      answered.push(`Q: ${q.q}\nA: (skipped)`);
      continue;
    }

    if (choice === OTHER_SENTINEL) {
      let typed: string | undefined;

      try {
        typed = await ctx.ui.input(q.q, "Type your answer");
      } catch {
        typed = undefined;
      }

      answered.push(
        `Q: ${q.q}\nA: ${typed?.trim() || "(no answer)"}`,
      );
    } else {
      answered.push(`Q: ${q.q}\nA: ${choice}`);
    }
  }

  return answered.join("\n\n");
}

async function orchestrate(
  pi: ExtensionAPI,
  ctx: any,
  prompt: string,
): Promise<void> {
  orchestrating = true;

  const abort = new AbortController();
  currentAbort = abort;

  // One continuous timer for the whole plan-mode process — every phase widget
  // counts from t0, so the user sees total elapsed throughout (not just the
  // per-sub-coder timers).
  const t0 = Date.now();

  const tracker = new SubCoderTracker(ctx, {
    key: "plan-explorers",
    totalSince: t0,
  });

  const status = new PlanStatus(ctx);

  // Per-phase model selection (issue #61). Switch the SESSION to the plan model
  // first, so the synthesis turn below — which runs on the main agent, not on a
  // sub-coder — is written by the planner too.
  //
  // Then read the model back rather than reusing the tag: enterPhase is a no-op
  // under manual handover and degrades to "stay put" when the model is
  // unavailable or has no key. Explorer sub-coders must follow what is actually
  // active, or a refused switch would send every child at a model this box
  // cannot serve — and on a single local backend, a child on a different model
  // forces a weight reload the user did not ask for.
  const switched = await enterPhase(pi, ctx, "plan");

  if (switched) {
    ctx.ui?.notify?.(switched, "info");
  }

  const model = currentModelId(ctx);

  // ESC (or Ctrl+C) cancels the plan: there's no agent turn running during the
  // research/question phases, so pi's built-in interrupt has nothing to abort —
  // we intercept the raw key ourselves and trip the AbortController.
  let escUnsub: (() => void) | null =
    ctx.ui?.onTerminalInput?.((data: string) => {
      if (data === "\x1b" || data === "\x03") {
        abort.abort();
        return { consume: true };
      }

      return undefined;
    }) ?? null;

  const dropEsc = () => {
    try {
      escUnsub?.();
    } catch {
      // ignore
    }

    escUnsub = null;
  };

  // The "submit a request" hint is done — plan mode is now working. Swap it for
  // the animated status line.
  setIndicator(ctx, false);

  try {
    status.start("deciding what to explore…", t0);

    const targets = await decomposeTargets(
      prompt,
      ctx.cwd,
      model,
      abort.signal,
    );

    if (abort.signal.aborted) return;

    const items: SubCoderItem[] = targets.map((t, i) => ({
      id: String(i + 1),
      label: t.label,
      task: t.task,
      cwd: ctx.cwd,
    }));

    // Hand the visual off to the tracker for the research phase — running both
    // animated aboveEditor widgets at once made the panel flicker.
    status.stop();

    tracker.begin(
      items.map((it) => ({
        id: it.id,
        label: it.label,
      })),
    );

    const results = await runSubCodersConcurrent(items, {
      model,
      signal: abort.signal,
      onUpdate: (all) => tracker.update(all),
    });

    tracker.end();

    if (abort.signal.aborted) return;

    const digest = digestReports(results);

    status.start("preparing clarifying questions…", t0);

    const questions = await generateQuestions(
      prompt,
      digest,
      ctx.cwd,
      model,
      abort.signal,
    );

    if (abort.signal.aborted) return;

    // Questions are ready: stop the animation and stop intercepting ESC so the
    // dialogs (and the synthesis turn after) handle their own keys.
    status.stop();
    dropEsc();

    const answers =
      questions.length > 0
        ? await askQuestions(ctx, questions)
        : "(no clarifying questions)";

    if (abort.signal.aborted) return;

    // Hand the synthesis to the main agent so the plan appears in the chat. The
    // user-visible message is their ORIGINAL request; the planning instructions
    // + research digest + answers are injected into this turn's system prompt
    // (see the before_agent_start handler) so they never show in the chat.
    // Edits/writes are blocked during this turn — plan mode produces a plan.
    planGuardActive = true;
    synthesisActive = true;
    pendingSynthesis = { digest, answers };

    ctx.ui?.notify?.("plan mode: writing the plan…", "info");

    pi.sendUserMessage(prompt);
  } catch (e) {
    ctx.ui?.notify?.(
      `plan mode failed: ${(e as Error)?.message ?? e}`,
      "error",
    );
  } finally {
    if (abort.signal.aborted) {
      ctx.ui?.notify?.("plan mode cancelled", "info");
    }

    dropEsc();
    status.stop();
    tracker.end();

    orchestrating = false;
    currentAbort = null;

    // One request per plan-mode activation — drop back to normal mode.
    planModeOn = false;
    setIndicator(ctx, false);
  }
}

export default function (pi: ExtensionAPI) {
  // ctrl+q toggles plan mode. pi leaves ctrl+q unbound and the emacs-style editor
  // doesn't claim it either (ctrl+y is its yank, so binding there both warned and
  // clobbered paste), so this collides with nothing and shift+tab stays bound to
  // pi's thinking-level cycle (issue #47). Raw mode disables flow control, so
  // ctrl+q is a clean \x11 byte on every terminal — unlike alt+p, which many
  // terminals deliver as a literal "π" rather than ESC+p, so the toggle never fired.
  pi.registerShortcut("ctrl+q", {
    description: "Toggle plan mode",

    handler: (ctx: any) => {
      if (orchestrating) return;

      planModeOn = !planModeOn;

      setIndicator(ctx, planModeOn);

      ctx.ui?.notify?.(
        planModeOn ? "plan mode on" : "plan mode off",
        "info",
      );
    },
  });

  // issue #98:
  //
  // Session replacement is deliberately initiated from a command handler.
  // pi's command context owns newSession(); event handlers such as agent_end do
  // not. This also gives the user explicit control over when the approved plan
  // leaves the planning context and begins implementation.
  pi.registerCommand("implement", {
    description: "Implement the last approved plan in a fresh session",

    handler: async (_args, ctx) => {
      const planFile = join(ctx.cwd, APPROVED_PLAN_FILE);

      await handleImplement({
        cwd: ctx.cwd,
        planFile,
        ui: ctx.ui ?? { notify: () => {} },
        fs: { readFileSync, mkdirSync, writeFileSync },
        pi,
        ctx,
        enterPhase,
        newSession: (opts) => ctx.newSession(opts),
      });
    },
  });

  // Intercept a submitted prompt while plan mode is on and run the orchestration
  // instead of a normal coding turn.
  pi.on("input", async (event, ctx) => {
    if (!planModeOn) return;
    if ((event as any).source !== "interactive") return;

    const text = String((event as any).text ?? "").trim();

    // Let commands and bash through untouched even in plan mode.
    if (!text || text.startsWith("/") || text.startsWith("!")) {
      return;
    }

    if (orchestrating) {
      (ctx as any).ui?.notify?.(
        "a plan is already in progress…",
        "warning",
      );

      return {
        action: "handled" as const,
      };
    }

    // Fire-and-forget: returning {handled} suppresses the normal turn; the
    // orchestration (dialogs, sub-coders, final synthesis) runs after.
    void orchestrate(pi, ctx, text);

    return {
      action: "handled" as const,
    };
  });

  // Inject the planning instructions + research into the synthesis turn, kept
  // out of the visible chat so it shows only the user's original request and
  // the model's plan — never the verbose internal instructions. Delivered as a
  // hidden tail message rather than a system-prompt append so the cached
  // prefix survives the turn (issue #73 — see _shared/inject.ts).
  pi.on("before_agent_start", async (event) => {
    if (!pendingSynthesis) return;

    const { digest, answers } = pendingSynthesis;
    pendingSynthesis = null;

    const block =
      `\n\n## Plan Mode\n` +
      `The user's message is a request to PLAN, not to implement. Write a concrete, ` +
      `well-structured implementation plan as your reply, using the research findings ` +
      `and the user's answers below. Output the plan as text only — do NOT edit or ` +
      `create files.\n\n` +
      `### Research findings\n${digest}\n\n` +
      `### User's answers to clarifying questions\n${answers}`;

    return injectionResult(
      "lc-plan",
      block,
      (event as any).systemPrompt ?? "",
    );
  });

  // While synthesizing the plan, block any attempt to edit/write files.
  pi.on("tool_call", async (event, ctx) => {
    if (!planGuardActive) return;

    const name = String(
      (event as any).toolName ?? "",
    ).toLowerCase();

    if (name !== "edit" && name !== "write") {
      return;
    }

    (ctx as any).ui?.notify?.(
      "harness intervention: plan mode — emit the plan as text, not file changes.",
      "info",
    );

    return {
      block: true,
      reason:
        "Plan mode is active: produce the implementation plan as text in your reply. Do NOT edit or create files.",
    };
  });

  // When the synthesis turn ends, capture the generated plan and let the user
  // approve it. Approval persists the plan only. It deliberately does not
  // switch to the action model, replace the session, or begin implementation.
  // The user starts that destructive transition explicitly with /implement.
  pi.on("agent_end", async (_event, ctx) => {
    planGuardActive = false;

    if (!synthesisActive) return;

    synthesisActive = false;

    const messages = (_event as any).messages ?? [];
    const planText = extractPlanText(messages);

    let choice: string | undefined;

    try {
      choice = await (ctx as any).ui?.select?.(
        "Plan ready — approve it?",
        [
          APPROVE_CHOICE,
          KEEP_PLANNING_CHOICE,
        ],
      );
    } catch {
      choice = undefined;
    }

    const planFile = join(
      ctx.cwd,
      APPROVED_PLAN_FILE,
    );

    handlePlanApproval({
      planText,
      approved: choice === APPROVE_CHOICE,
      planFile,
      fs: {
        writeFileSync,
        mkdirSync,
        readFileSync,
      },
      ui: ctx.ui ?? {
        notify: () => {},
      },
    });
  });

  // A new/resumed session resets all plan-mode state. It opens in plan mode when
  // launched with --plan-mode / LITTLE_CODER_PLAN_MODE=1 (issue #84), otherwise
  // off as before; ctrl+q still toggles from there.
  pi.on("session_start", async (_event, ctx) => {
    orchestrating = false;
    planGuardActive = false;
    synthesisActive = false;
    pendingSynthesis = null;

    if (currentAbort) {
      currentAbort.abort();
    }

    currentAbort = null;

    planModeOn = wantsPlanModeAtStart();

    setIndicator(ctx, planModeOn);
  });
}