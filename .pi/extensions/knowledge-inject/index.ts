import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { readdirSync, readFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { parseSkillFile } from "../skill-inject/frontmatter.ts";
import { injectionResult, makeDedupe } from "../_shared/inject.ts";

// ── Knowledge-entry registry ────────────────────────────────────────────
// Port of local/knowledge_augment.py. Loads skills/knowledge/*.md plus the
// three root-level protocol skills (skills/protocols/*.md). Scores entries
// against the user's prompt, selects top within budget, publishes
// `requires_tools` on systemPromptOptions so skill-inject can include them.
//
// Like skill-inject, the selected entries ride in as a tail message rather
// than a system-prompt append (issue #73 — see _shared/inject.ts).

interface KnowledgeEntry {
  topic: string;
  body: string;
  tokenCost: number;
  keywords: string[];
  requiresTools: string[];
}

const entries = new Map<string, KnowledgeEntry>();
const cache = new Map<string, string>();
let loaded = false;

const MIN_SCORE_THRESHOLD = 2.0;
const PER_ENTRY_CAP = 150;

function dirs(): string[] {
  const here = dirname(fileURLToPath(import.meta.url));
  const repo = join(here, "..", "..", "..");
  return [join(repo, "skills", "knowledge"), join(repo, "skills", "protocols")];
}

function loadEntries(): void {
  if (loaded) return;
  loaded = true;
  for (const dir of dirs()) {
    if (!existsSync(dir)) continue;
    for (const file of readdirSync(dir)) {
      if (!file.endsWith(".md")) continue;
      const parsed = parseSkillFile(readFileSync(join(dir, file), "utf-8"));
      if (!parsed) continue;
      const fm = parsed.frontmatter;
      const topic = (typeof fm.topic === "string" ? fm.topic : "") ||
                    (typeof fm.name === "string" ? fm.name : "");
      if (!topic || !parsed.body) continue;
      let cost = typeof fm.token_cost === "number" ? fm.token_cost : 150;
      if (cost > PER_ENTRY_CAP) cost = PER_ENTRY_CAP;
      const keywords = Array.isArray(fm.keywords)
        ? (fm.keywords as string[]).map((k) => k.toLowerCase())
        : [];
      const requiresTools = Array.isArray(fm.requires_tools)
        ? (fm.requires_tools as string[])
        : [];
      entries.set(topic, { topic, body: parsed.body, tokenCost: cost, keywords, requiresTools });
    }
  }
}

// ── Scoring (word=1.0, bigram/phrase=2.0) ───────────────────────────────
function scoreEntry(userText: string, e: KnowledgeEntry): number {
  if (e.keywords.length === 0) return 0;
  const textLower = userText.toLowerCase();
  const words = new Set(textLower.split(/\s+/).filter(Boolean));
  let score = 0;
  for (const kw of e.keywords) {
    if (kw.includes(" ")) {
      if (textLower.includes(kw)) score += 2.0;
    } else {
      if (words.has(kw)) score += 1.0;
    }
  }
  return score;
}

function estimateTokens(text: string): number {
  return Math.ceil(text.length / 3.5);
}

function buildBlock(selected: KnowledgeEntry[]): string {
  let out = "\n\n## Algorithm Reference\n";
  for (const e of selected) out += `\n### ${e.topic}\n${e.body}\n`;
  return out;
}

export default function (pi: ExtensionAPI) {
  const shouldInject = makeDedupe();

  pi.on("before_agent_start", async (event, ctx) => {
    loadEntries();
    if (entries.size === 0) return;

    const opts: any = (event as any).systemPromptOptions ?? {};
    const lc = opts.littleCoder ?? {};
    const budget: number = lc.knowledgeTokenBudget ?? 200;
    if (budget <= 0) return;
    if (lc.isSubtask) return;

    const base = event.systemPrompt ?? "";
    const contextLimit: number = lc.contextLimit ?? 8192;
    if (estimateTokens(base) > contextLimit * 0.4) return;

    const prompt = event.prompt ?? "";
    if (!prompt) return;

    const scored: Array<{ score: number; entry: KnowledgeEntry }> = [];
    for (const e of entries.values()) {
      const s = scoreEntry(prompt, e);
      if (s >= MIN_SCORE_THRESHOLD) scored.push({ score: s, entry: e });
    }
    if (scored.length === 0) return;
    scored.sort((a, b) => b.score - a.score);

    const selected: KnowledgeEntry[] = [];
    let used = 0;
    for (const { entry } of scored) {
      if (used + entry.tokenCost > budget) continue;
      selected.push(entry);
      used += entry.tokenCost;
    }
    if (selected.length === 0) return;

    // Publish required tools on systemPromptOptions. skill-inject reads this
    // to include the requires_tools' skill cards in its own selection.
    const requiredTools = Array.from(
      new Set(selected.flatMap((e) => e.requiresTools)),
    );
    if (requiredTools.length > 0) {
      if (!opts.littleCoder) opts.littleCoder = {};
      opts.littleCoder.requiredTools = requiredTools;
    }

    const key = selected.map((e) => e.topic).sort().join("|");
    let block = cache.get(key);
    if (block === undefined) {
      block = buildBlock(selected);
      cache.set(key, block);
    }

    // Same entries as last turn? That copy is still in the conversation.
    if (!shouldInject(block)) return;

    try {
      ctx.ui.notify(
        `knowledge-inject: +${selected.length} [${selected.map((e) => e.topic).join(",")}]`,
        "info",
      );
    } catch {
      // best-effort
    }

    return injectionResult("lc-knowledge", block, base);
  });
}
