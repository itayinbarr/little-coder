import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { readdirSync, readFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { parseSkillFile } from "./frontmatter.ts";
import { injectionResult, makeDedupe } from "../_shared/inject.ts";
import { allowedToolSet, toolsAvailable } from "../_shared/allowed-tools.ts";

// ── Tool-skill registry ─────────────────────────────────────────────────
// Port of local/skill_augment.py. Loads skills/tools/*.md once, hooks
// `before_agent_start` to add a `## Tool Usage Guidance` block to the turn.
// Per-user-prompt selection using the whitepaper's 3-priority algorithm
// (error recovery > recency > intent). Budget-guarded, cached.
//
// The block is delivered as a tail message rather than appended to the system
// prompt — see _shared/inject.ts for why (issue #73: it was invalidating the
// KV cache on every turn).

interface ToolSkill {
  targetTool: string;
  body: string;
  tokenCost: number;
}

const skills = new Map<string, ToolSkill>();
const selectionCache = new Map<string, string>();
let loaded = false;

// State tracked across the session so we have error-recovery + recency
// signals by the time the next `before_agent_start` fires.
const recentToolCalls: string[] = []; // most-recent-first, capped at 8
let lastFailedTool: string | null = null;
// Set by `/skills <tool>`: forces that card into the next selection ahead of
// every automatic signal. Cleared by `/skills off` (issue #118).
let pinnedSkill: string | null = null;

// ── Intent keywords → likely tools ──────────────────────────────────────
const INTENT_MAP: Record<string, string[]> = {
  read: ["read"], show: ["read"], view: ["read"], cat: ["read"],
  write: ["write"], create: ["write", "bash"],
  implement: ["write", "read"], code: ["write", "read"],
  function: ["write", "edit"], class: ["write", "edit"],
  edit: ["edit"], change: ["edit"], modify: ["edit"],
  fix: ["edit"], update: ["edit"], replace: ["edit"],
  add: ["edit", "write"], refactor: ["edit", "read"],
  run: ["bash"], execute: ["bash"],
  // Long-running intents point at ShellStart first: these are exactly the
  // commands that would otherwise block a whole turn on `bash`.
  install: ["ShellStart", "bash"], build: ["ShellStart", "bash"],
  test: ["bash"],
  train: ["ShellStart"], training: ["ShellStart"], finetune: ["ShellStart"],
  background: ["ShellStart"], watch: ["ShellStart"], serve: ["ShellStart"],
  server: ["ShellStart"], monitor: ["ShellStart"], daemon: ["ShellStart"],
  find: ["glob", "grep"], search: ["grep"],
  grep: ["grep"], glob: ["glob"],
  fetch: ["webfetch"], download: ["webfetch"], url: ["webfetch"],
  web: ["websearch"],
  // Research / browser / evidence
  research: ["BrowserNavigate", "BrowserExtract", "EvidenceAdd"],
  researching: ["BrowserNavigate", "BrowserExtract", "EvidenceAdd"],
  wikipedia: ["BrowserNavigate", "BrowserExtract", "EvidenceAdd"],
  article: ["BrowserNavigate", "BrowserExtract", "EvidenceAdd"],
  citation: ["EvidenceAdd", "BrowserExtract"],
  cite: ["EvidenceAdd"],
  source: ["EvidenceAdd", "BrowserExtract"],
  fact: ["EvidenceAdd"],
  factcheck: ["EvidenceAdd", "BrowserExtract"],
  question: ["EvidenceAdd", "BrowserExtract"],
  answer: ["EvidenceAdd", "EvidenceList"],
  navigate: ["BrowserNavigate"],
  browse: ["BrowserNavigate", "BrowserExtract"],
  page: ["BrowserExtract"],
  click: ["BrowserClick"],
  // Sub-coder delegation
  delegate: ["dispatch"], dispatch: ["dispatch"], subagent: ["dispatch"],
  investigate: ["dispatch"], parallel: ["dispatch"],
};

function skillsDir(): string {
  // Extension lives at .pi/extensions/skill-inject/, repo root is 3 levels up
  const here = dirname(fileURLToPath(import.meta.url));
  return join(here, "..", "..", "..", "skills", "tools");
}

function loadSkills(): void {
  if (loaded) return;
  loaded = true;
  const dir = skillsDir();
  if (!existsSync(dir)) return;
  for (const file of readdirSync(dir)) {
    if (!file.endsWith(".md")) continue;
    const parsed = parseSkillFile(readFileSync(join(dir, file), "utf-8"));
    if (!parsed) continue;
    const target = parsed.frontmatter.target_tool;
    if (typeof target !== "string" || !target) continue;
    const cost = typeof parsed.frontmatter.token_cost === "number"
      ? parsed.frontmatter.token_cost
      : 150;
    skills.set(target, { targetTool: target, body: parsed.body, tokenCost: cost });
  }
}

function predictTools(userText: string): string[] {
  const words = new Set(userText.toLowerCase().split(/\s+/).filter(Boolean));
  const predicted: string[] = [];
  for (const [kw, toolNames] of Object.entries(INTENT_MAP)) {
    if (!words.has(kw)) continue;
    for (const tn of toolNames) if (!predicted.includes(tn)) predicted.push(tn);
  }
  return predicted;
}

// Resolve a tool name to its skill card case-insensitively.
//
// The registry is keyed by each card's `target_tool`, but the recency and
// error-recovery lookups feed it names straight off pi's tool events. When pi
// 0.83 renamed its built-ins to lowercase, every one of those lookups started
// missing silently and priorities 1 and 2 of the selection algorithm stopped
// contributing anything — only intent prediction still fired, and nothing
// failed loudly enough to notice. Matching case-insensitively means a future
// rename degrades to "the card still loads" instead of "half the algorithm is
// dead". `allowed` is checked against the tool's real registered name.
function lookupSkill(name: string): ToolSkill | undefined {
  const direct = skills.get(name);
  if (direct) return direct;
  const lower = name.toLowerCase();
  for (const [key, sk] of skills) {
    if (key.toLowerCase() === lower) return sk;
  }
  return undefined;
}

/** One line per loaded card, for `/skills`. Sorted, so the output is stable. */
export function skillInventory(): { tool: string; tokens: number; pinned: boolean }[] {
  loadSkills();
  return [...skills.entries()]
    .map(([tool, sk]) => ({ tool, tokens: sk.tokenCost, pinned: tool === pinnedSkill }))
    .sort((a, b) => a.tool.localeCompare(b.tool));
}

/** Resolve `/skills <arg>` to the new pin. Returns the message to show.
 *  Pure apart from the pin itself, so the argument handling is testable. */
export function applySkillsCommand(arg: string): string {
  const name = arg.trim();
  if (!name) {
    const rows = skillInventory();
    if (rows.length === 0) return "no tool skill cards are loaded";
    return [
      `${rows.length} tool skill cards loaded (selected automatically per turn):`,
      ...rows.map((r) => `  ${r.pinned ? "*" : " "} ${r.tool}  ~${r.tokens} tok`),
      pinnedSkill
        ? `pinned: ${pinnedSkill} (clear with /skills off)`
        : "pin one with /skills <tool>, clear with /skills off",
    ].join("\n");
  }
  if (name === "off" || name === "none" || name === "clear") {
    pinnedSkill = null;
    return "skill pin cleared; selection is automatic again";
  }
  const sk = lookupSkill(name);
  if (!sk) {
    const known = skillInventory().map((r) => r.tool).join(", ");
    return `no skill card for "${name}". Loaded: ${known || "(none)"}`;
  }
  pinnedSkill = sk.targetTool;
  return `pinned the ${sk.targetTool} skill card (~${sk.tokenCost} tok); it is injected every turn until /skills off`;
}

function selectSkills(prompt: string, budget: number, allowed?: Set<string>): ToolSkill[] {
  const selected: ToolSkill[] = [];
  let used = 0;
  const tryAdd = (name: string): void => {
    const sk = lookupSkill(name);
    if (!sk || selected.includes(sk)) return;
    if (allowed && !allowed.has(name)) return;
    if (used + sk.tokenCost > budget) return;
    selected.push(sk);
    used += sk.tokenCost;
  };

  // 0. An explicit pin from `/skills <tool>` outranks every automatic signal.
  //    That is the whole point of pinning: the user has already seen the
  //    selector pick the wrong card and is overriding it (issue #118).
  if (pinnedSkill) tryAdd(pinnedSkill);

  // 1. Error recovery — last failed tool
  if (lastFailedTool) tryAdd(lastFailedTool);

  // 2. Recency — last 2 tool calls
  for (const name of recentToolCalls.slice(0, 4)) {
    if (used >= budget) break;
    tryAdd(name);
  }

  // 3. Intent prediction on the user's current prompt
  if (used < budget) {
    for (const name of predictTools(prompt)) {
      if (used >= budget) break;
      tryAdd(name);
    }
  }

  return selected;
}

// A card is selected for its own target_tool, but its prose may point at other
// tools — browser_extract tells you to save the span you found via EvidenceAdd.
// In a sub-coder that call is refused (issue #97), so drop any guidance line
// naming a gated tool rather than instructing a dead end. Only whole lines are
// dropped, which keeps the surrounding card intact.
function stripGatedLines(body: string, allowed: Set<string> | undefined): string {
  if (!allowed) return body;
  const gated = EVIDENCE_TOOLS.filter((t) => !allowed.has(t));
  if (gated.length === 0) return body;
  return body
    .split("\n")
    .filter((line) => !gated.some((t) => line.includes(t)))
    .join("\n");
}

function buildBlock(selected: ToolSkill[], allowed?: Set<string>): string {
  let out = "\n\n## Tool Usage Guidance\n";
  for (const s of selected) {
    out += `\n### ${s.targetTool}\n${stripGatedLines(s.body, allowed)}\n`;
  }
  return out;
}

// Keyword-triggered directive: when the user's prompt smells like a
// research / web-lookup task, prepend an explicit "browse-first, then
// edit-write" rule. Without it, qwen-class small models often skip
// straight to edit/write on free-form questions, never gathering evidence.
const RESEARCH_TRIGGERS = [
  /\bbrows(?:e|ing|er)\b/i,
  /\bonline\b/i,
  /\bresearch(?:ing)?\b/i,
  /\blook\s+up\b/i,
  /\blookup\b/i,
  /\bsearch\s+(?:the|for)\b/i,
  /\bweb\s*search\b/i,
  /\bwikipedia\b/i,
  /\bwebsite\b/i,
  /\bweb\s*page\b/i,
  /\bgoogle\b/i,
  /\bcite|citation\b/i,
  /\bfact[-\s]?check/i,
];

function looksLikeResearchTask(text: string): boolean {
  if (!text) return false;
  for (const re of RESEARCH_TRIGGERS) {
    if (re.test(text)) return true;
  }
  return false;
}

// Built per-turn rather than as a constant: the evidence step only makes sense
// when the evidence tools are actually callable. In a sub-coder they are not
// (SUBCODER_ALLOWED_TOOLS has no Evidence*), and instructing a child to "save
// each citable fact via EvidenceAdd" when tool-gating will refuse the call is
// how issue #97 presented. Children cite inline in their report instead.
const EVIDENCE_TOOLS = ["EvidenceAdd", "EvidenceGet", "EvidenceList"];

function researchDirective(allowed: Set<string> | undefined): string {
  const canCite = toolsAvailable(["EvidenceAdd"], allowed);
  const lines = [
    "",
    "## Research-first directive",
    "This task involves online research. Before producing a final answer:",
    "1. Use BrowserNavigate / BrowserExtract (or websearch for first hops) to gather facts.",
  ];
  if (canCite) {
    lines.push("2. Save each citable fact via EvidenceAdd before relying on it.");
    lines.push("3. Only after evidence is in place should you consider any edit/write tool calls.");
    lines.push(
      "Skipping the gather step (going straight to edit/write or guessing from memory) is wrong — restart with the browse step instead.",
    );
  } else {
    lines.push("2. Quote the exact span you rely on and name its source URL inline in your report.");
    lines.push("3. Only after the facts are gathered should you state a conclusion.");
    lines.push(
      "Skipping the gather step (guessing from memory) is wrong — restart with the browse step instead.",
    );
  }
  lines.push("");
  return lines.join("\n");
}

export default function (pi: ExtensionAPI) {
  // `/skills` (issue #118). pi's own `/skill:name` addresses pi skills; these
  // cards are a different mechanism (selected per turn by error-recovery >
  // recency > intent and injected at the conversation tail), so pi's command
  // cannot see them. This lists what is loaded, and pins one when the selector
  // keeps choosing a different card than the one you want.
  pi.registerCommand("skills", {
    description: "List loaded tool skill cards; /skills <tool> pins one, /skills off clears it",
    handler: async (args: string, ctx: any) => {
      const message = applySkillsCommand(args ?? "");
      ctx.ui?.notify?.(message, "info");
    },
  });

  const shouldInject = makeDedupe();

  // Track tool usage across the whole session so recency + error-recovery
  // state is available on the next before_agent_start.
  pi.on("tool_result", async (event) => {
    const name = (event as any).toolName || (event as any).name;
    if (typeof name === "string") {
      // prepend, keep deduplicated recency list capped
      const idx = recentToolCalls.indexOf(name);
      if (idx !== -1) recentToolCalls.splice(idx, 1);
      recentToolCalls.unshift(name);
      if (recentToolCalls.length > 8) recentToolCalls.length = 8;
    }
    const isError = (event as any).isError === true;
    lastFailedTool = isError && typeof name === "string" ? name : null;
  });

  pi.on("before_agent_start", async (event, ctx) => {
    loadSkills();
    if (skills.size === 0) return;

    const opts: any = (event as any).systemPromptOptions ?? {};
    const lc = opts.littleCoder ?? {};
    const budget: number = lc.skillTokenBudget ?? 300;
    if (budget <= 0) return;

    // Allow-list source: prefer systemPromptOptions (set by tool-gating's
    // before_agent_start), falling back to LITTLE_CODER_ALLOWED_TOOLS env
    // directly. Pi runs before_agent_start handlers in extension load order
    // (alphabetical), so skill-inject fires before tool-gating and
    // lc.allowedTools is undefined on the first turn unless we read env here.
    const allowed = allowedToolSet(lc);

    // Knowledge-inject may publish required_tools on systemPromptOptions —
    // pre-add those before selecting so they win even when budget is tight.
    // Benchmark profiles can also publish requiredTools (e.g. GAIA -> Browser+Evidence).
    const preferred: string[] = Array.isArray(lc.requiredTools) ? lc.requiredTools : [];
    for (const t of preferred) {
      if (!recentToolCalls.includes(t)) recentToolCalls.unshift(t);
    }

    const selected = selectSkills(event.prompt ?? "", budget, allowed);
    const researchTask = looksLikeResearchTask(event.prompt ?? "");

    if (selected.length === 0 && !researchTask) return;

    const skillBlock = selected.length > 0
      ? (() => {
          // The gated set is part of the key: the same card renders differently
          // once a gated tool's guidance lines are stripped out.
          const gateKey = allowed ? `#${EVIDENCE_TOOLS.filter((t) => !allowed.has(t)).join(",")}` : "";
          const key = selected.map((s) => s.targetTool).sort().join("|") + gateKey;
          let b = selectionCache.get(key);
          if (b === undefined) {
            b = buildBlock(selected, allowed);
            selectionCache.set(key, b);
          }
          return b;
        })()
      : "";

    const directive = researchTask ? researchDirective(allowed) : "";

    // Order within the block: [tool skill cards] [research directive]. The
    // directive comes LAST by design — small models show strong recency bias
    // and the per-task instruction is what we want freshest in their
    // attention. Delivered at the conversation tail (see _shared/inject.ts),
    // which is later still than the end of the system prompt.
    const block = skillBlock + directive;

    // Identical to last turn's block? The previous copy is still in the
    // conversation, so re-sending it would only burn context.
    if (!shouldInject(block)) return;

    // Fire-and-forget notify so the benchmark harness can count per-turn
    // skill injections without having to reconstruct the prompt.
    try {
      const parts: string[] = [];
      if (selected.length > 0) {
        parts.push(`+${selected.length} [${selected.map((s) => s.targetTool).join(",")}]`);
      }
      if (researchTask) parts.push("+research-directive");
      ctx.ui.notify(`skill-inject: ${parts.join(" ")}`, "info");
    } catch {
      // UI unavailable in some run modes — silent best-effort
    }

    return injectionResult("lc-skills", block, event.systemPrompt ?? "");
  });
}
