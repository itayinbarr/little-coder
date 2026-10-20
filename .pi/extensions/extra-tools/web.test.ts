import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SessionManager } from "@earendil-works/pi-coding-agent";
import { AsyncLocalStorage } from "node:async_hooks";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import setup from "./index.ts";

const endpoint = "https://search.parallel.ai/mcp";
const excerpt = "Node documentation\nhttps://nodejs.org/api/\nUse AbortSignal to cancel requests.";
type Request = { url: string; headers: Headers; body: any; signal?: AbortSignal | null };
let requests: Request[];

function register(manager = SessionManager.inMemory()) {
  const tools = new Map<string, any>();
  const context = new AsyncLocalStorage<SessionManager>();
  setup({
    registerTool: (tool: any) => tools.set(tool.name, tool),
    appendEntry: (type: string, data: unknown) => context.getStore()!.appendCustomEntry(type, data),
  } as any);
  return (name: string, args: object, signal?: AbortSignal, activeManager = manager) =>
    context.run(activeManager, () => tools.get(name).execute("call", args, signal, undefined, { sessionManager: activeManager }));
}

function mockMcp(result: object = { content: [{ type: "text", text: excerpt }] }) {
  vi.stubGlobal("fetch", vi.fn(async (input: URL | string, init?: RequestInit) => {
    const body = init?.body ? JSON.parse(String(init.body)) : undefined;
    requests.push({ url: String(input), headers: new Headers(init?.headers), body, signal: init?.signal });
    if (body?.method === "initialize") {
      return Response.json({ jsonrpc: "2.0", id: body.id, result: {
        protocolVersion: "2025-03-26", capabilities: { tools: {} },
        serverInfo: { name: "fixture", version: "1" },
      } });
    }
    if (body?.method === "notifications/initialized") return new Response(null, { status: 202 });
    if (body?.method === "tools/call") return Response.json({ jsonrpc: "2.0", id: body.id, result });
    return new Response(null, { status: 405 });
  }));
}

beforeEach(() => {
  requests = [];
  vi.stubEnv("LITTLE_CODER_WEB_PROVIDER", "parallel");
  // Ambient provider keys must never authenticate the anonymous integration.
  vi.stubEnv("PARALLEL_API_KEY", "unused-sentinel");
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

describe("registered web tools", () => {
  it("keeps DuckDuckGo and direct fetch as the unconfigured and explicit defaults", async () => {
    for (const provider of ["", "duckduckgo"]) {
      vi.stubEnv("LITTLE_CODER_WEB_PROVIDER", provider);
      const fetcher = vi.fn(async (_input: unknown, _init?: RequestInit) => new Response('<h2 class="result__title"><a href="https://nodejs.org/">Node</a></h2><div class="result__snippet">Docs</div>'));
      vi.stubGlobal("fetch", fetcher);
      const call = register();
      const result = await call("websearch", { query: "node & abort" });
      expect(result.content[0].text).toContain("https://nodejs.org/");
      expect(String(fetcher.mock.calls[0][0])).toBe("https://html.duckduckgo.com/html/?q=node%20%26%20abort");
      await call("webfetch", { url: "https://nodejs.org/api/" });
      expect(String(fetcher.mock.calls[1][0])).toBe("https://nodejs.org/api/");
    }
  });

  it("executes the MCP transport and returns URLs/excerpts through the original tool contract", async () => {
    mockMcp();
    const manager = SessionManager.inMemory();
    const call = register(manager);
    const result = await call("websearch", { query: "node abort signal" });
    expect(result.content).toEqual([{ type: "text", text: excerpt }]);
    expect(result.isError).toBeUndefined();
    await call("webfetch", { url: "https://nodejs.org/api/", prompt: "cancellation" });
    const calls = requests.filter((r) => r.body?.method === "tools/call");
    expect(calls.map((r) => r.body.params)).toEqual([
      { name: "web_search", arguments: { objective: "node abort signal", search_queries: ["node abort signal"], session_id: manager.getSessionId() } },
      { name: "web_fetch", arguments: { urls: ["https://nodejs.org/api/"], objective: "cancellation", session_id: manager.getSessionId() } },
    ]);
    expect(requests.some((r) => r.body?.method === "initialize")).toBe(true);
    for (const r of requests) {
      expect(r.url).toBe(endpoint);
      expect(r.headers.get("User-Agent")).toBe("little-coder (https://github.com/itayinbarr/little-coder)");
      expect(r.headers.has("Authorization")).toBe(false);
    }
  });

  it("keeps conversation identity for follow-ups and retries, isolates interleaved chats and resets", async () => {
    mockMcp();
    const a = SessionManager.inMemory(), b = SessionManager.inMemory();
    const callA = register(a), callB = register(b);
    await Promise.all([callA("websearch", { query: "A" }), callB("websearch", { query: "B" })]);
    await callA("webfetch", { url: "https://example.com/A" });
    mockMcp({ isError: true, content: [{ type: "text", text: "quota exceeded" }] });
    await callA("websearch", { query: "retry A" });
    mockMcp();
    await callA("websearch", { query: "retry A" });
    const oldId = a.getSessionId();
    a.newSession();
    await callA("websearch", { query: "new A" });
    const args = requests.filter((r) => r.body?.method === "tools/call").map((r) => r.body.params.arguments);
    expect(args.filter((x) => x.objective?.includes("A") && x.objective !== "new A").every((x) => x.session_id === oldId)).toBe(true);
    expect(args.find((x) => x.urls)?.session_id).toBe(oldId);
    expect(args.find((x) => x.objective === "B").session_id).toBe(b.getSessionId());
    expect(b.getSessionId()).not.toBe(oldId);
    expect(args.at(-1).session_id).toBe(a.getSessionId());
    expect(a.getSessionId()).not.toBe(oldId);
    expect(oldId).toMatch(/^[0-9a-f-]{36}$/);
  });

  it("reports bad configuration and invalid fetch URLs without requests", async () => {
    mockMcp();
    vi.stubEnv("LITTLE_CODER_WEB_PROVIDER", "typo");
    expect((await register()("websearch", { query: "node" })).isError).toBe(true);
    vi.stubEnv("LITTLE_CODER_WEB_PROVIDER", "parallel");
    for (const url of ["not a url", "file:///etc/passwd", "data:text/plain,hi"]) {
      expect((await register()("webfetch", { url })).isError).toBe(true);
    }
    expect(requests).toHaveLength(0);
  });

  it("replaces custom/long session labels with opaque IDs owned by each conversation header", async () => {
    mockMcp();
    const a = SessionManager.inMemory(), b = SessionManager.inMemory();
    const label = "personal-session-label-".repeat(10) + "end";
    a.newSession({ id: label }); b.newSession({ id: label });
    const call = register(a);
    await Promise.all([
      call("websearch", { query: "A" }),
      call("websearch", { query: "B" }, undefined, b),
    ]);
    await call("webfetch", { url: "https://example.com" });
    await call("websearch", { query: "A follow-up" });
    a.newSession({ id: label });
    await call("websearch", { query: "reset A" });
    const args = requests.filter((r) => r.body?.method === "tools/call").map((r) => r.body.params.arguments);
    const idA = args.find((x) => x.objective === "A").session_id;
    const idB = args.find((x) => x.objective === "B").session_id;
    expect(idA).toMatch(/^[0-9a-f-]{36}$/);
    expect(idB).toMatch(/^[0-9a-f-]{36}$/);
    expect(idA).not.toBe(idB);
    expect(args.find((x) => x.urls).session_id).toBe(idA);
    expect(args.find((x) => x.objective === "A follow-up").session_id).toBe(idA);
    expect(args.at(-1).session_id).not.toBe(idA);
    expect(JSON.stringify(requests)).not.toContain(label);
  });

  it("caps excerpts and fetch objectives", async () => {
    mockMcp({ content: [{ type: "text", text: "x".repeat(30_000) }] });
    expect((await register()("webfetch", { url: "https://example.com", prompt: "a".repeat(300) })).content[0].text).toHaveLength(25_000);
    expect(requests.find((r) => r.body?.method === "tools/call")?.body.params.arguments.objective).toHaveLength(200);
  });

  it("persists custom conversation UUIDs across resume/reload but isolates copied metadata in a new session", async () => {
    mockMcp();
    const dir = mkdtempSync(join(tmpdir(), "little-coder-web-resume-"));
    try {
      const path = join(dir, "session.jsonl");
      writeFileSync(path, [
        { type: "session", version: 3, id: "custom-label", timestamp: "2026-01-01T00:00:00.000Z", cwd: dir },
        { type: "message", id: "seed", parentId: null, timestamp: "2026-01-01T00:00:01.000Z", message: {
          role: "assistant", content: [{ type: "text", text: "Ready" }], api: "openai-completions", provider: "fixture", model: "fixture",
          usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
          stopReason: "stop", timestamp: 0,
        } },
      ].map((entry) => JSON.stringify(entry)).join("\n") + "\n");
      const manager = SessionManager.open(path);
      const call = register(manager);
      await call("websearch", { query: "first" });
      const header = manager.getHeader();
      const metadata = manager.getEntries().find((entry) => entry.type === "custom")!;
      manager.setSessionFile(path);
      expect(manager.getHeader()).not.toBe(header);
      await call("webfetch", { url: "https://example.com" });
      const reopened = SessionManager.open(path);
      await register(reopened)("websearch", { query: "fresh extension after resume" });
      manager.createBranchedSession(manager.getLeafId()!);
      await call("websearch", { query: "forked conversation" });
      // A copied entry from the old conversation must not identify a new header.
      reopened.newSession({ id: "custom-label" });
      reopened.appendCustomEntry((metadata as any).customType, (metadata as any).data);
      await register(reopened)("websearch", { query: "new conversation" });
      const args = requests.filter((r) => r.body?.method === "tools/call").map((r) => r.body.params.arguments);
      expect(args[0].session_id).toBe(args[1].session_id);
      expect(args[0].session_id).toBe(args[2].session_id);
      expect(args[3].session_id).not.toBe(args[0].session_id);
      expect(args[4].session_id).not.toBe(args[0].session_id);
      expect(JSON.stringify(requests)).not.toContain("custom-label");
    } finally { rmSync(dir, { recursive: true, force: true }); }
  });

  it("surfaces MCP errors and malformed content without a fallback", async () => {
    for (const result of [
      { isError: true, content: [{ type: "text", text: "quota exceeded" }] },
      { content: [] },
    ]) {
      mockMcp(result);
      expect((await register()("websearch", { query: "node" })).isError).toBe(true);
      expect(requests.every((r) => r.url === endpoint)).toBe(true);
    }
    vi.stubGlobal("fetch", vi.fn(async () => new Response("unavailable", { status: 503 })));
    const result = await register()("websearch", { query: "node" });
    expect(result.isError).toBe(true);
    expect(result.content[0].text).toContain("unavailable");
  });

  it.each(["cancel", "timeout"])("aborts a pending handshake on %s", async (reason) => {
    const controller = new AbortController();
    if (reason === "timeout") vi.spyOn(AbortSignal, "timeout").mockReturnValue(controller.signal);
    let started!: () => void;
    const ready = new Promise<void>((resolve) => { started = resolve; });
    vi.stubGlobal("fetch", vi.fn((_input, init) => new Promise((_resolve, reject) => {
      started();
      init.signal.addEventListener("abort", () => reject(init.signal.reason), { once: true });
    })));
    const pending = register()("websearch", { query: "node" }, reason === "cancel" ? controller.signal : undefined);
    await ready;
    controller.abort(new DOMException(reason, reason === "timeout" ? "TimeoutError" : "AbortError"));
    expect((await pending).isError).toBe(true);
  });

  it.each(["cancel", "timeout"])("aborts a pending tool response body on %s", async (reason) => {
    mockMcp();
    const fixtureFetch = fetch;
    const controller = new AbortController();
    if (reason === "timeout") vi.spyOn(AbortSignal, "timeout").mockReturnValue(controller.signal);
    let started!: () => void;
    const ready = new Promise<void>((resolve) => { started = resolve; });
    vi.stubGlobal("fetch", vi.fn(async (input, init) => {
      if (init?.body && JSON.parse(String(init.body)).method === "tools/call") {
        return new Response(new ReadableStream({ start(stream) {
          init.signal.addEventListener("abort", () => stream.error(init.signal.reason), { once: true });
          started();
        } }), { headers: { "content-type": "application/json" } });
      }
      return fixtureFetch(input, init);
    }));
    const pending = register()("webfetch", { url: "https://example.com" }, reason === "cancel" ? controller.signal : undefined);
    await ready;
    controller.abort(new DOMException(reason, reason === "timeout" ? "TimeoutError" : "AbortError"));
    expect((await pending).isError).toBe(true);
  });

  it("consumes an HTTP SSE tool response", async () => {
    mockMcp();
    const fixtureFetch = fetch;
    vi.stubGlobal("fetch", vi.fn(async (input, init) => {
      const body = init?.body ? JSON.parse(String(init.body)) : undefined;
      if (body?.method === "tools/call") {
        return new Response(`event: message\ndata: ${JSON.stringify({ jsonrpc: "2.0", id: body.id,
          result: { content: [{ type: "text", text: excerpt }] } })}\n\n`,
        { headers: { "content-type": "text/event-stream" } });
      }
      return fixtureFetch(input, init);
    }));
    expect((await register()("websearch", { query: "node" })).content[0].text).toBe(excerpt);
  });
});
