import { describe, it, expect } from "vitest";
import { buildPlaceholder, pruneMessages } from "./index.ts";

// Canned message shapes mirror pi's AgentMessage / ToolResultMessage.
// See node_modules/@mariozechner/pi-ai/dist/types.d.ts for the real types.

function userMsg(text: string) {
  return { role: "user", content: text };
}

function assistantNavigate(url: string) {
  return {
    role: "assistant",
    content: [
      { type: "text", text: `Let me fetch ${url}` },
      { type: "toolCall", id: "c1", name: "BrowserNavigate", arguments: { url } },
    ],
  };
}

function assistantExtract(cursor = 0) {
  return {
    role: "assistant",
    content: [
      { type: "toolCall", id: "c2", name: "BrowserExtract", arguments: { cursor: String(cursor) } },
    ],
  };
}

function extractResult(text: string, cursor = 0, next = 2048, total = 10000) {
  return {
    role: "toolResult",
    toolCallId: "c2",
    toolName: "BrowserExtract",
    content: [{ type: "text", text: `${text}\n[cursor=${cursor} next=${next} total=${total} has_more=true]` }],
    isError: false,
    timestamp: Date.now(),
  };
}

describe("buildPlaceholder", () => {
  it("includes URL and character count", () => {
    const p = buildPlaceholder("https://example.com", 18432, []);
    expect(p).toContain("URL: https://example.com");
    expect(p).toContain("18432 chars");
    expect(p).toContain("No EvidenceAdd calls yet");
  });

  it("lists matching evidence entries with IDs and notes", () => {
    const ev = [
      { id: "e3a1", source: "https://example.com/article", note: "key fact X", snippet: "..." },
      { id: "e7c2", source: "https://example.com/article", note: "detail Y", snippet: "..." },
    ];
    const p = buildPlaceholder("https://example.com/article", 12000, ev);
    expect(p).toContain("e3a1 (key fact X)");
    expect(p).toContain("e7c2 (detail Y)");
  });

  it("handles unknown URL gracefully", () => {
    const p = buildPlaceholder(undefined, 500, []);
    expect(p).toContain("URL: (unknown");
  });
});

describe("pruneMessages", () => {
  it("no-op when no BrowserExtract results in history", () => {
    const msgs = [userMsg("hello"), { role: "assistant", content: [{ type: "text", text: "hi" }] }];
    const out = pruneMessages(msgs, 2, []);
    expect(out.prunedCount).toBe(0);
    expect(out.messages).toEqual(msgs);
  });

  it("retains the 2 most recent BrowserExtract raw; prunes older", () => {
    const msgs = [
      userMsg("research this"),
      assistantNavigate("https://example.com"),
      assistantExtract(0),
      extractResult("chunk A"),              // oldest — should prune
      assistantExtract(2048),
      extractResult("chunk B"),              // rank 1 — keep raw
      assistantExtract(4096),
      extractResult("chunk C"),              // rank 0 (newest) — keep raw
    ];
    const out = pruneMessages(msgs, 2, []);
    expect(out.prunedCount).toBe(1);
    expect(out.messages[3].content[0].text).toContain("pruned");
    expect(out.messages[5].content[0].text).toContain("chunk B");   // retained
    expect(out.messages[7].content[0].text).toContain("chunk C");   // retained
  });

  it("pruned placeholder cites the correct URL via walk-back to BrowserNavigate", () => {
    const msgs = [
      userMsg("task"),
      assistantNavigate("https://site-a.com"),
      assistantExtract(0),
      extractResult("a-content"),             // oldest — prune, URL=site-a
      assistantNavigate("https://site-b.com"),
      assistantExtract(0),
      extractResult("b-content"),             // keep raw
      assistantExtract(2048),
      extractResult("b-content-2"),           // keep raw
    ];
    const out = pruneMessages(msgs, 2, []);
    expect(out.messages[3].content[0].text).toContain("URL: https://site-a.com");
    expect(out.messages[3].content[0].text).not.toContain("site-b");
  });

  it("matching evidence by source substring", () => {
    const evidence = [
      { id: "e1", source: "https://en.wikipedia.org/wiki/Topic_X", note: "founded in 1847", snippet: "..." },
      { id: "e2", source: "https://en.wikipedia.org/wiki/Topic_X", note: "population 100k", snippet: "..." },
      { id: "e3", source: "https://other.site",                    note: "irrelevant",      snippet: "..." },
    ];
    const msgs = [
      userMsg("t"),
      assistantNavigate("https://en.wikipedia.org/wiki/Topic_X"),
      assistantExtract(0),
      extractResult("page-1"),                // prune, should cite e1+e2 not e3
      assistantExtract(2048),
      extractResult("page-2"),
      assistantExtract(4096),
      extractResult("page-3"),
    ];
    const out = pruneMessages(msgs, 2, evidence);
    const pruned = out.messages[3].content[0].text;
    expect(pruned).toContain("e1 (founded in 1847)");
    expect(pruned).toContain("e2 (population 100k)");
    expect(pruned).not.toContain("e3");
  });

  it("idempotent — already-pruned messages aren't re-pruned", () => {
    const msgs = [
      userMsg("t"),
      assistantNavigate("https://a.com"),
      assistantExtract(0),
      extractResult("fresh"),                     // oldest
      assistantExtract(2048),
      extractResult("keep-raw-1"),
      assistantExtract(4096),
      extractResult("keep-raw-2"),
    ];
    const out1 = pruneMessages(msgs, 2, []);
    expect(out1.prunedCount).toBe(1);
    const out2 = pruneMessages(out1.messages, 2, []);
    expect(out2.prunedCount).toBe(0);   // second pass is no-op
  });

  it("prunes 3 of 5 when retain=2 and 5 extracts exist", () => {
    const msgs: any[] = [userMsg("t"), assistantNavigate("https://x.com")];
    for (let i = 0; i < 5; i++) {
      msgs.push(assistantExtract(i * 2048));
      msgs.push(extractResult(`chunk ${i}`));
    }
    const out = pruneMessages(msgs, 2, []);
    expect(out.prunedCount).toBe(3);   // oldest 3 pruned, newest 2 raw
  });

  it("retain=0 prunes all BrowserExtract results", () => {
    const msgs = [
      userMsg("t"),
      assistantNavigate("https://x.com"),
      assistantExtract(0),
      extractResult("c1"),
      assistantExtract(2048),
      extractResult("c2"),
    ];
    const out = pruneMessages(msgs, 0, []);
    expect(out.prunedCount).toBe(2);
  });

  it("only touches BrowserExtract results, not other tool results", () => {
    const msgs = [
      userMsg("t"),
      {
        role: "toolResult",
        toolCallId: "c9",
        toolName: "BrowserNavigate",  // different tool — must not prune
        content: [{ type: "text", text: "navigated" }],
        isError: false,
        timestamp: Date.now(),
      },
      assistantNavigate("https://a.com"),
      assistantExtract(0),
      extractResult("older"),
      assistantExtract(2048),
      extractResult("middle"),
      assistantExtract(4096),
      extractResult("newest"),
    ];
    const out = pruneMessages(msgs, 2, []);
    expect(out.prunedCount).toBe(1);
    // BrowserNavigate toolResult untouched
    expect(out.messages[1].content[0].text).toBe("navigated");
  });
});
