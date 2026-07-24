import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { readdirSync, readFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { parseSkillFile } from "./frontmatter.ts";
import { injectionResult, makeDedupe } from "../_shared/inject.ts";

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

// ── Intent keywords → likely tools ──────────────────────────────────────
const INTENT_MAP: Record<string, string[]> = {
  read: ["Read"], show: ["Read"], view: ["Read"], cat: ["Read"],
  write: ["Write"], create: ["Write", "Bash"],
  implement: ["Write", "Read"], code: ["Write", "Read"],
  function: ["Write", "Edit"], class: ["Write", "Edit"],
  edit: ["Edit"], change: ["Edit"], modify: ["Edit"],
  fix: ["Edit"], update: ["Edit"], replace: ["Edit"],
  add: ["Edit", "Write"], refactor: ["Edit", "Read"],
  run: ["Bash"], execute: ["Bash"], install: ["Bash"],
  build: ["Bash"], test: ["Bash"],
  find: ["Glob", "Grep"], search: ["Grep"],
  grep: ["Grep"], glob: ["Glob"],
  fetch: ["WebFetch"], download: ["WebFetch"], url: ["WebFetch"],
  web: ["WebSearch"],
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

function selectSkills(prompt: string, budget: number, allowed?: Set<string>): ToolSkill[] {
  const selected: ToolSkill[] = [];
  let used = 0;
  const tryAdd = (name: string): void => {
    const sk = skills.get(name);
    if (!sk || selected.includes(sk)) return;
    if (allowed && !allowed.has(name)) return;
    if (used + sk.tokenCost > budget) return;
    selected.push(sk);
    used += sk.tokenCost;
  };

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

function buildBlock(selected: ToolSkill[]): string {
  let out = "\n\n## Tool Usage Guidance\n";
  for (const s of selected) out += `\n### ${s.targetTool}\n${s.body}\n`;
  return out;
}

// Keyword-triggered directive: when the user's prompt smells like a
// research / web-lookup task, prepend an explicit "browse-first, then
// edit-write" rule. Without it, qwen-class small models often skip
// straight to Edit/Write on free-form questions, never gathering evidence.
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

const RESEARCH_DIRECTIVE = [
  "",
  "## Research-first directive",
  "This task involves online research. Before producing a final answer:",
  "1. Use BrowserNavigate / BrowserExtract (or WebSearch for first hops) to gather facts.",
  "2. Save each citable fact via EvidenceAdd before relying on it.",
  "3. Only after evidence is in place should you consider any Edit/Write tool calls.",
  "Skipping the gather step (going straight to Edit/Write or guessing from memory) is wrong — restart with the browse step instead.",
  "",
].join("\n");

export default function (pi: ExtensionAPI) {
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
    // before_agent_start), but fall back to LITTLE_CODER_ALLOWED_TOOLS env
    // directly. Pi runs before_agent_start handlers in extension load order
    // (alphabetical), so skill-inject fires before tool-gating and
    // lc.allowedTools is undefined on the first turn unless we read env here.
    let allowedList: string[] | undefined = lc.allowedTools;
    if (!allowedList && process.env.LITTLE_CODER_ALLOWED_TOOLS) {
      allowedList = process.env.LITTLE_CODER_ALLOWED_TOOLS
        .split(",").map((s) => s.trim()).filter(Boolean);
    }
    const allowed = allowedList && allowedList.length > 0 ? new Set(allowedList) : undefined;

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
          const key = selected.map((s) => s.targetTool).sort().join("|");
          let b = selectionCache.get(key);
          if (b === undefined) {
            b = buildBlock(selected);
            selectionCache.set(key, b);
          }
          return b;
        })()
      : "";

    const directive = researchTask ? RESEARCH_DIRECTIVE : "";

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
