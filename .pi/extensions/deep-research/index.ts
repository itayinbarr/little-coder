import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { getFinalText } from "../subagent/spawn.ts";
import { currentModelId } from "../subagent/index.ts";
import { PlanStatus } from "../plan-mode/status.ts";
import { terminalColumns, truncateLineToWidth } from "../_shared/width.ts";
import { injectionResult } from "../_shared/inject.ts";
import { allocateBudget, clampAgents, MAX_AGENTS, MIN_AGENTS } from "./budget.ts";
import { ResearchProgress } from "./progress-bar.ts";
import { reportFilename, resolveMaxDefault } from "./helpers.ts";
import { writeInstructionBlock } from "./prompts.ts";
import { runResearchPhases, type Question } from "./pipeline.ts";

// Deep Research — a Scope → Research → Write flow, sibling to plan mode.
//
// f2 toggles deep-research mode (an indicator appears below the input); the next
// submitted prompt becomes the research TOPIC. `/deep-research <topic>` is an
// equivalent entry (and a reliable fallback where a terminal doesn't deliver f2).
// While a run is active the extension orchestrates, from the parent process:
//   0. ask the user a max-agents cap M (1-10),
//   1. Scope: 1-4 clarifying questions → a compressed research brief (north star),
//   2. Lead: split the brief into wave-1 research subtopics (the "1 agent"),
//   3. Research: dispatch read-only research sub-coders (isolated context; only
//      their concise findings survive), shown as a rectangle PROGRESS BAR — not
//      the per-child subagent view,
//   4. Gap-fill: the lead reviews wave-1 findings and, if needed, spawns 1-2 more,
//   5. Write: the MAIN agent writes ONE cited markdown report from brief + findings
//      (a sub-coder's report is capped at 2000 chars — too small for a report),
//   6. save the report to deep-research-<slug>-<ts>.md and exit the mode.
//
// f2 is decoded by pi-tui (f1-f12) and is claimed by neither pi's app keybindings,
// the emacs-style editor, nor another extension (plan-mode owns ctrl+q,
// shortcuts-help owns ctrl+h — and every other ctrl+<letter> is taken by the app
// or the editor), so it binds cleanly without a conflict warning.

const honey = (s: string) => `\x1b[38;2;225;90;31m${s}\x1b[39m`;
const gray = (s: string) => `\x1b[90m${s}\x1b[39m`;
const INDICATOR_KEY = "deep-research-mode";
const OTHER_SENTINEL = "✎ Other (type my own answer)";

let deepResearchOn = false;
let orchestrating = false;
let currentAbort: AbortController | null = null;
// Set just before the write turn; consumed by before_agent_start to inject the
// brief + findings + report instructions into the system prompt (kept out of the
// visible chat). Null at all other times.
let pendingReport: { topic: string; brief: string; digest: string; failedCount: number } | null = null;
// Set alongside pendingReport so agent_end can name + place the saved file.
let reportTopic = "";
let reportCwd = "";
// True while the write turn is in flight — its agent_end saves the report file.
let writeReportActive = false;
// True during the write turn — blocks edit/write so the report is text, not files.
let reportGuardActive = false;

// ---- config -----------------------------------------------------------------

let maxDefault = MAX_AGENTS;
let settingsLoaded = false;

function repoRoot(): string {
  const here = dirname(fileURLToPath(import.meta.url));
  return join(here, "..", "..", "..");
}

function loadMaxDefault(): number {
  if (settingsLoaded) return maxDefault;
  settingsLoaded = true;
  let settings: { deep_research?: { default_max_subagents?: number } } | null = null;
  const candidates = [
    join(repoRoot(), ".pi", "settings.json"),
    join(process.env.HOME ?? "", ".pi", "agent", "settings.json"),
  ];
  for (const p of candidates) {
    if (!existsSync(p)) continue;
    try {
      const raw = JSON.parse(readFileSync(p, "utf-8"));
      if (raw && typeof raw === "object" && raw.little_coder) {
        settings = raw.little_coder;
        break;
      }
    } catch {
      // ignore malformed settings
    }
  }
  maxDefault = resolveMaxDefault(process.env, settings);
  return maxDefault;
}

// ---- indicator --------------------------------------------------------------

function indicatorLines(): string[] {
  const raw = `${honey("◇")} ${honey("DEEP RESEARCH")}  ${gray("(f2 to exit)")}`;
  return [truncateLineToWidth(raw, terminalColumns())];
}

function setIndicator(ctx: any, on: boolean): void {
  if (!ctx?.hasUI) return;
  ctx.ui.setWidget(INDICATOR_KEY, on ? indicatorLines() : undefined, { placement: "belowEditor" });
}

// ---- user prompts -----------------------------------------------------------

function parseAgentChoice(choice: string | undefined, def: number): number {
  if (!choice) return def;
  const n = Number(choice.replace(/[^0-9]/g, ""));
  return Number.isFinite(n) && n >= MIN_AGENTS ? clampAgents(n) : def;
}

async function askMaxAgents(ctx: any, def: number): Promise<number> {
  if (!ctx?.hasUI) return def;
  // Default first so Enter picks it; then the rest ascending.
  const rest: string[] = [];
  for (let i = MIN_AGENTS; i <= MAX_AGENTS; i++) if (i !== def) rest.push(String(i));
  const options = [`${def} (default)`, ...rest];
  let choice: string | undefined;
  try {
    choice = await ctx.ui.select(`Max research agents (${MIN_AGENTS}-${MAX_AGENTS})`, options);
  } catch {
    choice = undefined;
  }
  return parseAgentChoice(choice, def);
}

async function askQuestions(ctx: any, questions: Question[]): Promise<string> {
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
      answered.push(`Q: ${q.q}\nA: ${typed?.trim() || "(no answer)"}`);
    } else {
      answered.push(`Q: ${q.q}\nA: ${choice}`);
    }
  }
  return answered.join("\n\n");
}

// ---- orchestration ----------------------------------------------------------

async function orchestrate(pi: ExtensionAPI, ctx: any, topic: string): Promise<void> {
  orchestrating = true;
  const abort = new AbortController();
  currentAbort = abort;
  const t0 = Date.now();
  const status = new PlanStatus(ctx, "deep-research-status");
  const progress = new ResearchProgress(ctx);
  const model = currentModelId(ctx);
  // Research/reasoning children run in an ephemeral scratch dir, never the user's
  // project: research agents (read + browse, no bash — see pipeline.ts) still
  // shouldn't have the working tree as their cwd, and this guarantees a research
  // run can never leave files behind in the user's repo. Removed in `finally`.
  let scratchDir: string | null = null;
  try {
    scratchDir = mkdtempSync(join(tmpdir(), "deep-research-"));
  } catch {
    scratchDir = null; // fall back to cwd if tmp isn't writable
  }

  // ESC / Ctrl+C cancels during the non-agent phases (research/reasoning), where
  // pi's built-in interrupt has no turn to abort. We arm/disarm around UI dialogs
  // so the select/input prompts keep their own ESC-to-cancel behavior.
  let escUnsub: (() => void) | null = null;
  const arm = () => {
    if (escUnsub || !ctx.ui?.onTerminalInput) return;
    escUnsub = ctx.ui.onTerminalInput((data: string) => {
      if (data === "\x1b" || data === "\x03") {
        abort.abort();
        return { consume: true };
      }
      return undefined;
    });
  };
  const disarm = () => {
    try {
      escUnsub?.();
    } catch {
      /* ignore */
    }
    escUnsub = null;
  };

  setIndicator(ctx, false);
  try {
    // 0. Cap.
    const M = await askMaxAgents(ctx, loadMaxDefault());
    if (abort.signal.aborted) return;
    const budget = allocateBudget(M);

    // Phases 1-4 run through the shared pipeline (pipeline.ts) — the same code
    // the batch eval exercises. UI is driven via hooks: reasoning phases animate
    // the status spinner, research waves drive the progress bar, and the
    // clarifying-question dialog drops the ESC interceptor so it owns its keys.
    arm();
    const result = await runResearchPhases(topic, {
      budget,
      cwd: scratchDir ?? ctx.cwd,
      model,
      signal: abort.signal,
      hooks: {
        askAnswers: async (questions: Question[]) => {
          status.stop();
          disarm();
          const ans = await askQuestions(ctx, questions);
          arm();
          return ans;
        },
        onReasoning: (message: string) => status.start(message, t0),
        onResearchBegin: (total: number) => {
          status.stop();
          progress.begin(total, "researching", t0);
        },
        onResearchProgress: (done: number, total: number, phase: string) => progress.update(done, total, phase),
        onResearchEnd: () => progress.end(),
      },
    });
    if (abort.signal.aborted || result.aborted) return;

    // 5. Write — hand to the main agent so the full report lands in chat; its
    // agent_end saves it to a file. The user-visible message is their topic; the
    // brief + findings + instructions are injected into the system prompt.
    disarm();
    reportTopic = topic;
    reportCwd = ctx.cwd;
    pendingReport = { topic, brief: result.brief, digest: result.digest, failedCount: result.meta.failedSubagents };
    writeReportActive = true;
    reportGuardActive = true;
    ctx.ui?.notify?.("deep research: writing the report…", "info");
    pi.sendUserMessage(topic);
  } catch (e) {
    ctx.ui?.notify?.(`deep research failed: ${(e as Error)?.message ?? e}`, "error");
  } finally {
    if (abort.signal.aborted) ctx.ui?.notify?.("deep research cancelled", "info");
    disarm();
    status.stop();
    progress.end();
    if (scratchDir) {
      try {
        rmSync(scratchDir, { recursive: true, force: true });
      } catch {
        /* best effort */
      }
    }
    orchestrating = false;
    currentAbort = null;
    // One research run per activation — drop back to normal mode. (The write turn
    // + its guard/save state persist; they are cleared by their own handlers.)
    deepResearchOn = false;
    setIndicator(ctx, false);
  }
}

// Shared entry used by both the f2 toggle and the /deep-research command.
function startRun(pi: ExtensionAPI, ctx: any, topic: string): void {
  if (orchestrating) {
    ctx.ui?.notify?.("a research run is already in progress…", "warning");
    return;
  }
  void orchestrate(pi, ctx, topic);
}

export default function (pi: ExtensionAPI) {
  loadMaxDefault();

  // f2 toggles deep-research mode.
  pi.registerShortcut("f2", {
    description: "Toggle deep research mode",
    handler: (ctx: any) => {
      if (orchestrating) return; // mid-run: ignore toggles
      deepResearchOn = !deepResearchOn;
      setIndicator(ctx, deepResearchOn);
      ctx.ui?.notify?.(deepResearchOn ? "deep research on — submit a topic" : "deep research off", "info");
    },
  });

  // /deep-research [topic] — run directly with the topic, or arm the mode.
  pi.registerCommand("deep-research", {
    description: "Deep research: scope → research → one-shot cited report",
    handler: async (args: string, ctx: any) => {
      const topic = (args ?? "").trim();
      if (topic) {
        startRun(pi, ctx, topic);
      } else {
        deepResearchOn = true;
        setIndicator(ctx, true);
        ctx.ui?.notify?.("deep research on — submit a topic", "info");
      }
    },
  });

  // Intercept a submitted prompt while the mode is on and run the research flow
  // instead of a normal coding turn.
  pi.on("input", async (event, ctx) => {
    if (!deepResearchOn) return;
    if ((event as any).source !== "interactive") return;
    const text = String((event as any).text ?? "").trim();
    if (!text || text.startsWith("/") || text.startsWith("!")) return;
    if (orchestrating) {
      (ctx as any).ui?.notify?.("a research run is already in progress…", "warning");
      return { action: "handled" as const };
    }
    startRun(pi, ctx as any, text);
    return { action: "handled" as const };
  });

  // Inject the report-writing instructions + brief + findings into the write
  // turn, hidden from the transcript so the chat shows only the topic and the
  // model's report. Delivered as a tail message rather than a system-prompt
  // append (issue #73 — see _shared/inject.ts); for a findings digest this
  // size, rewriting the system prompt meant reprocessing the whole context.
  pi.on("before_agent_start", async (event) => {
    if (!pendingReport) return;
    const { topic, brief, digest, failedCount } = pendingReport;
    pendingReport = null;
    return injectionResult(
      "lc-research",
      writeInstructionBlock(topic, brief, digest, failedCount),
      (event as any).systemPrompt ?? "",
    );
  });

  // Block edit/write/bash during the write turn — deep research produces a report
  // as text (we save it ourselves in agent_end); the write agent must not touch
  // the working tree (bash included, so it can't scaffold/compile either).
  pi.on("tool_call", async (event, ctx) => {
    if (!reportGuardActive) return;
    const name = String((event as any).toolName ?? "").toLowerCase();
    if (name !== "edit" && name !== "write" && name !== "bash") return;
    (ctx as any).ui?.notify?.("harness intervention: deep research — emit the report as text.", "info");
    return {
      block: true,
      reason: "Deep research is writing the report: produce it as text in your reply. Do NOT edit, create files, or run commands.",
    };
  });

  // When the write turn ends, save its report to a markdown file next to the cwd.
  pi.on("agent_end", async (event, ctx) => {
    reportGuardActive = false;
    if (!writeReportActive) return;
    writeReportActive = false;
    const report = getFinalText((event as any).messages ?? []).trim();
    if (!report) {
      (ctx as any).ui?.notify?.("deep research: no report text produced", "warning");
      return;
    }
    try {
      const file = reportFilename(reportTopic, new Date());
      const path = join(reportCwd || (ctx as any).cwd, file);
      writeFileSync(path, report.endsWith("\n") ? report : report + "\n", "utf-8");
      (ctx as any).ui?.notify?.(`deep research report saved → ${file}`, "info");
    } catch (e) {
      (ctx as any).ui?.notify?.(`deep research: could not save report (${(e as Error)?.message ?? e})`, "error");
    }
  });

  // A new/resumed session resets all deep-research state.
  pi.on("session_start", async (_event, ctx) => {
    deepResearchOn = false;
    orchestrating = false;
    writeReportActive = false;
    reportGuardActive = false;
    pendingReport = null;
    if (currentAbort) currentAbort.abort();
    currentAbort = null;
    setIndicator(ctx, false);
  });
}
