import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { getSessionStore } from "../evidence/index.ts";

// Post-turn pruning of BrowserExtract tool-result messages.
//
// Why this exists: BrowserExtract returns 2 KB chunks of raw page text,
// and each chunk sits in the agent's message history. On a GAIA trial
// reading several pages, the model accumulates 20-40 KB of raw text in
// context while separately saving the relevant bits via EvidenceAdd.
// The raw text is redundant post-distillation and contaminates context
// for subsequent reasoning.
//
// Policy: the 2 MOST-RECENT BrowserExtract tool-results stay raw (the
// model may still be deciding what to evidence-add from them). Older
// ones get replaced with a compact placeholder that cites:
//   - the URL they came from (found by walking back for the most recent
//     BrowserNavigate toolCall)
//   - the total original size
//   - the Evidence entry IDs whose `source` field matches the URL
//
// Evidence entries themselves are stored out-of-band in the evidence
// extension's session store and are untouched by this pruning — the
// model can EvidenceGet any of them on demand.

const DEFAULT_RETAIN_RAW = 2; // keep this many newest BrowserExtract results raw

function isToolResult(m: any): boolean {
  return m?.role === "toolResult";
}

function isBrowserExtractResult(m: any): boolean {
  if (!isToolResult(m)) return false;
  return m.toolName === "BrowserExtract";
}

function contentText(m: any): string {
  if (typeof m?.content === "string") return m.content;
  if (Array.isArray(m?.content)) {
    return m.content
      .filter((c: any) => c?.type === "text")
      .map((c: any) => c.text ?? "")
      .join("\n");
  }
  return "";
}

function isAlreadyPruned(m: any): boolean {
  return contentText(m).startsWith("[BrowserExtract tool-result pruned");
}

/**
 * Walk backward from the extract message to find the most recent
 * BrowserNavigate toolCall — that's the URL the extract came from.
 * Returns undefined if no navigation precedes this extract.
 */
function findUrlForExtract(messages: any[], extractIdx: number): string | undefined {
  for (let i = extractIdx - 1; i >= 0; i--) {
    const m = messages[i];
    if (m?.role !== "assistant") continue;
    const content = Array.isArray(m.content) ? m.content : [];
    for (const block of content) {
      if (block?.type !== "toolCall") continue;
      if (block.name === "BrowserNavigate") {
        const url = block.arguments?.url ?? block.input?.url;
        if (typeof url === "string") return url;
      }
      if (block.name === "BrowserBack") {
        // BrowserBack leaves us on whatever page we were before — need to
        // walk further to find the earlier navigation. Continue loop.
      }
    }
  }
  return undefined;
}

/**
 * Count preceding BrowserExtract tool-results (at indices before this one).
 * Used to decide which are in the "retain raw" newest-N set and which get
 * pruned. The newest (highest index) is rank 0; older ones have higher rank.
 */
function extractRankFromEnd(
  messages: any[],
  thisIdx: number,
): number {
  let rank = 0;
  for (let i = thisIdx + 1; i < messages.length; i++) {
    if (isBrowserExtractResult(messages[i]) && !isAlreadyPruned(messages[i])) rank++;
  }
  return rank;
}

function urlMatchesEvidenceSource(url: string, source: string): boolean {
  if (!url || !source) return false;
  // Be generous: either contains the other (handles minor URL variants
  // like trailing slash, query params, or the model using a short source
  // tag like "wikipedia" instead of the full URL).
  return source.includes(url) || url.includes(source);
}

interface EvidenceEntry {
  id: string;
  source: string;
  note: string;
  snippet: string;
}

export function buildPlaceholder(
  url: string | undefined,
  originalChars: number,
  evidenceFromThisUrl: EvidenceEntry[],
): string {
  const urlLine = url ? `URL: ${url}` : "URL: (unknown — see conversation above)";
  const evList = evidenceFromThisUrl.length > 0
    ? `Evidence saved from this extraction: ${evidenceFromThisUrl
        .map((e) => `${e.id} (${e.note})`)
        .join("; ")}. Use EvidenceGet <id> to recall any snippet.`
    : "No EvidenceAdd calls yet cited this URL — raw text was dropped from context.";
  return [
    `[BrowserExtract tool-result pruned — ${originalChars} chars originally extracted]`,
    urlLine,
    evList,
  ].join("\n");
}

export function pruneMessages(
  messages: any[],
  retainRaw: number,
  evidenceStore: EvidenceEntry[],
): { messages: any[]; prunedCount: number } {
  const result = [...messages];
  let prunedCount = 0;

  for (let i = 0; i < result.length; i++) {
    const m = result[i];
    if (!isBrowserExtractResult(m)) continue;
    if (isAlreadyPruned(m)) continue;
    const rank = extractRankFromEnd(result, i);
    if (rank < retainRaw) continue;

    const url = findUrlForExtract(result, i);
    const origChars = contentText(m).length;
    const matchingEvidence = url
      ? evidenceStore.filter((e) => urlMatchesEvidenceSource(url, e.source))
      : [];

    const placeholder = buildPlaceholder(url, origChars, matchingEvidence);
    result[i] = {
      ...m,
      content: [{ type: "text" as const, text: placeholder }],
    };
    prunedCount++;
  }

  return { messages: result, prunedCount };
}

export default function (pi: ExtensionAPI) {
  pi.on("context", async (event) => {
    const retainRaw = DEFAULT_RETAIN_RAW;
    const evidenceStore = getSessionStore() as EvidenceEntry[];
    const { messages, prunedCount } = pruneMessages(
      (event as any).messages || [],
      retainRaw,
      evidenceStore,
    );
    if (prunedCount > 0) {
      return { messages };
    }
  });
}
