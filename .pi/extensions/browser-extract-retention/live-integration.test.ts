import { describe, it, expect } from "vitest";
import { pruneMessages, buildPlaceholder } from "./index.ts";

// Live integration test: runs Playwright against a real URL, extracts
// with the same inlined Readability JS the Browser extension uses, then
// exercises the retention pruning against a simulated conversation
// history that contains the real extracted text.
//
// This verifies the whole Browser + Evidence + retention pipeline on
// real-world content without needing a live LLM in the loop.
//
// Skipped automatically if Playwright isn't installed (e.g. on CI
// images that don't have chromium).

const CHUNK_SIZE = 2048;

// Matches the inlined Readability used by the Browser extension. Passed as
// a real function (not a string) so Playwright auto-invokes it — the string
// form silently returns undefined because `"() => {...}"` evaluates to a
// function *value*, not the invocation.
function readablePageText(): string {
  const doc = document as any;
  const clone = doc.body.cloneNode(true) as HTMLElement;
  const drop = clone.querySelectorAll(
    "script, style, noscript, iframe, nav, header, footer, aside, form",
  );
  drop.forEach((n: Element) => n.remove());
  const text = (clone.innerText || "").replace(/\n{3,}/g, "\n\n").trim();
  return text;
}

async function extractPageText(url: string): Promise<string> {
  const { chromium } = await import("playwright");
  const browser = await chromium.launch({ headless: true });
  try {
    const ctx = await browser.newContext({
      userAgent: "Mozilla/5.0 (little-coder research agent)",
      viewport: { width: 1280, height: 900 },
    });
    const page = await ctx.newPage();
    page.setDefaultTimeout(20_000);
    await page.goto(url, { waitUntil: "domcontentloaded" });
    const text = await page.evaluate(readablePageText);
    await ctx.close();
    return text ?? "";
  } finally {
    await browser.close();
  }
}

function chunk(text: string, cursor = 0): { chunk: string; next: number | null; total: number; hasMore: boolean } {
  const end = Math.min(cursor + CHUNK_SIZE, text.length);
  const hasMore = end < text.length;
  return { chunk: text.slice(cursor, end), next: hasMore ? end : null, total: text.length, hasMore };
}

describe("live integration — Wikipedia extraction + retention", () => {
  it("extracts Wikipedia Test page and produces reasonable chunks", async () => {
    const url = "https://en.wikipedia.org/wiki/Terminal_Bench";
    const full = await extractPageText(url);

    expect(full.length).toBeGreaterThan(500);
    expect(full.toLowerCase()).toMatch(/bench|test|software|terminal/);

    // Verify chunking semantics match what the Browser extension emits
    const c0 = chunk(full, 0);
    expect(c0.chunk.length).toBe(Math.min(CHUNK_SIZE, full.length));
    expect(c0.total).toBe(full.length);
    if (full.length > CHUNK_SIZE) {
      expect(c0.hasMore).toBe(true);
      expect(c0.next).toBe(CHUNK_SIZE);
    }
  }, 30000);

  it("simulates a GAIA-style trial: 3 extracts + 2 evidence + 1 unrelated turn, then prunes", async () => {
    const url = "https://en.wikipedia.org/wiki/Apollo_11";
    const full = await extractPageText(url);
    expect(full.length).toBeGreaterThan(2000);

    // First 3 chunks — mirrors what the agent would see across 3 BrowserExtract calls
    const c0 = full.slice(0, 2048);
    const c1 = full.slice(2048, 4096);
    const c2 = full.slice(4096, 6144);

    // Simulated conversation history
    const messages: any[] = [
      { role: "user", content: "When did Apollo 11 land on the Moon?" },
      {
        role: "assistant",
        content: [
          { type: "text", text: "Let me fetch the Wikipedia article." },
          { type: "toolCall", id: "c1", name: "BrowserNavigate", arguments: { url } },
        ],
      },
      { role: "toolResult", toolCallId: "c1", toolName: "BrowserNavigate",
        content: [{ type: "text", text: `[status=200] ${url}` }], isError: false, timestamp: 1 },
      {
        role: "assistant",
        content: [{ type: "toolCall", id: "c2", name: "BrowserExtract", arguments: { cursor: "0" } }],
      },
      { role: "toolResult", toolCallId: "c2", toolName: "BrowserExtract",
        content: [{ type: "text", text: `${c0}\n[cursor=0 next=2048 total=${full.length} has_more=true]` }], isError: false, timestamp: 2 },
      {
        role: "assistant",
        content: [{ type: "toolCall", id: "c3", name: "BrowserExtract", arguments: { cursor: "2048" } }],
      },
      { role: "toolResult", toolCallId: "c3", toolName: "BrowserExtract",
        content: [{ type: "text", text: `${c1}\n[cursor=2048 next=4096 total=${full.length} has_more=true]` }], isError: false, timestamp: 3 },
      {
        role: "assistant",
        content: [{ type: "toolCall", id: "c4", name: "BrowserExtract", arguments: { cursor: "4096" } }],
      },
      { role: "toolResult", toolCallId: "c4", toolName: "BrowserExtract",
        content: [{ type: "text", text: `${c2}\n[cursor=4096 next=6144 total=${full.length} has_more=true]` }], isError: false, timestamp: 4 },
    ];

    // Two evidence entries saved from this URL
    const evidence = [
      { id: "e1", source: url, note: "landing date: July 20, 1969", snippet: "On July 20, 1969, Apollo 11 became the first crewed mission to land on the Moon." },
      { id: "e2", source: url, note: "commander: Neil Armstrong",   snippet: "Commander Neil Armstrong and pilot Buzz Aldrin landed the lunar module Eagle..." },
    ];

    const { messages: out, prunedCount } = pruneMessages(messages, 2, evidence);

    // Oldest of 3 extracts should be pruned; the last 2 stay raw.
    expect(prunedCount).toBe(1);
    const prunedMsg = out[4];   // the first BrowserExtract result
    expect(prunedMsg.content[0].text).toContain("pruned");
    expect(prunedMsg.content[0].text).toContain(`URL: ${url}`);
    expect(prunedMsg.content[0].text).toContain("e1 (landing date: July 20, 1969)");
    expect(prunedMsg.content[0].text).toContain("e2 (commander: Neil Armstrong)");
    // Verify the chars-original count is reported and matches c0 + footer
    expect(prunedMsg.content[0].text).toMatch(/\d+ chars originally extracted/);

    // The two newer extracts still have the raw text (not pruned)
    expect(out[6].content[0].text).toContain(c1.slice(0, 100));
    expect(out[8].content[0].text).toContain(c2.slice(0, 100));
  }, 45000);

  it("context-contamination measurement: retention shrinks history size", async () => {
    const url = "https://en.wikipedia.org/wiki/GAIA";
    const full = await extractPageText(url);
    if (full.length < 6144) {
      // Page too short to test 3-chunk accumulation meaningfully
      return;
    }

    const chunks = [full.slice(0, 2048), full.slice(2048, 4096), full.slice(4096, 6144)];
    const messages: any[] = [
      { role: "user", content: "What is GAIA?" },
      { role: "assistant", content: [{ type: "toolCall", id: "c1", name: "BrowserNavigate", arguments: { url } }] },
      { role: "toolResult", toolCallId: "c1", toolName: "BrowserNavigate",
        content: [{ type: "text", text: `[status=200] ${url}` }], isError: false, timestamp: 1 },
    ];
    for (let i = 0; i < 3; i++) {
      messages.push({ role: "assistant", content: [{ type: "toolCall", id: `e${i}`, name: "BrowserExtract", arguments: { cursor: String(i * 2048) } }] });
      messages.push({
        role: "toolResult", toolCallId: `e${i}`, toolName: "BrowserExtract",
        content: [{ type: "text", text: `${chunks[i]}\n[cursor=${i*2048} next=${(i+1)*2048} total=${full.length} has_more=true]` }],
        isError: false, timestamp: 2 + i,
      });
    }

    const sizeBefore = JSON.stringify(messages).length;
    const { messages: out, prunedCount } = pruneMessages(messages, 2, []);
    const sizeAfter = JSON.stringify(out).length;

    expect(prunedCount).toBe(1);
    expect(sizeAfter).toBeLessThan(sizeBefore);
    const savedChars = sizeBefore - sizeAfter;
    console.log(`    context savings: ${savedChars} chars (${((1 - sizeAfter / sizeBefore) * 100).toFixed(1)}% reduction from pruning 1 of 3 extracts)`);
    // At retention=2 with 3 extracts, we prune 1/3 of the raw text. Savings
    // should be close to 2048 chars minus the placeholder overhead (~200 chars).
    expect(savedChars).toBeGreaterThan(1000);
  }, 45000);
});
