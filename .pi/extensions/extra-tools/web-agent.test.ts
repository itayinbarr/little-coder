import { afterEach, expect, it, vi } from "vitest";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  createAgentSession, DefaultResourceLoader, ModelRuntime, SessionManager, SettingsManager,
  type AgentSession,
} from "@earendil-works/pi-coding-agent";
import setup from "./index.ts";
import gate from "../tool-gating/index.ts";

const sessions: AgentSession[] = [];
const dirs: string[] = [];
afterEach(() => {
  for (const session of sessions.splice(0)) session.dispose();
  for (const dir of dirs.splice(0)) rmSync(dir, { recursive: true, force: true });
  vi.unstubAllGlobals(); vi.unstubAllEnvs();
});

async function createSession(excludeTools: string[] = [], customId?: string) {
  const cwd = mkdtempSync(join(tmpdir(), "little-coder-web-"));
  dirs.push(cwd);
  const settingsManager = SettingsManager.inMemory({ compaction: { enabled: false }, retry: { enabled: false } });
  const modelRuntime = await ModelRuntime.create({ authPath: join(cwd, "auth.json"), modelsPath: null, modelsStorePath: join(cwd, "models-store.json") });
  modelRuntime.registerProvider("scripted-web-test", {
    api: "openai-completions", baseUrl: "http://127.0.0.1:1", apiKey: "scripted-only",
    models: [{ id: "scripted", name: "Scripted", reasoning: false, input: ["text"], contextWindow: 32768, maxTokens: 2048,
      cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } }],
  });
  const loader = new DefaultResourceLoader({
    cwd, agentDir: cwd, settingsManager,
    noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true,
    extensionFactories: [setup, gate],
  });
  await loader.reload();
  const manager = SessionManager.inMemory(cwd);
  if (customId) manager.newSession({ id: customId });
  const { session } = await createAgentSession({
    cwd, agentDir: cwd, modelRuntime, settingsManager, sessionManager: manager, resourceLoader: loader,
    model: modelRuntime.getModel("scripted-web-test", "scripted")!,
    tools: ["websearch", "webfetch"], excludeTools,
  });
  sessions.push(session);
  return { session, manager };
}

// This is a scripted model, not a live inference test. pi still owns extension
// loading, dispatch, permission hooks, tool-result history and conversation IDs.
function script(session: AgentSession, next: (context: any, turn: number) => any[]) {
  let turn = 0;
  session.agent.streamFunction = ((_model: any, context: any) => {
    const content = next(context, turn++);
    const message = {
      role: "assistant", content, api: "openai-completions", provider: "scripted-web-test", model: "scripted",
      stopReason: content.some((c) => c.type === "toolCall") ? "toolUse" : "stop", timestamp: Date.now(),
      usage: { input: 1, output: 1, cacheRead: 0, cacheWrite: 0, totalTokens: 2,
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
    };
    return {
      async *[Symbol.asyncIterator]() { yield { type: "start", partial: message }; yield { type: "done", reason: message.stopReason, message }; },
      result: async () => message,
    };
  }) as any;
}

it("pi dispatches search then fetch and delivers the excerpts back to the model in isolated sessions", async () => {
  vi.stubEnv("LITTLE_CODER_WEB_PROVIDER", "parallel");
  vi.stubEnv("PARALLEL_API_KEY", "unused-sentinel");
  const calls: any[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input, init) => {
    expect(String(input)).toBe("https://search.parallel.ai/mcp");
    const headers = new Headers(init.headers);
    expect(headers.get("user-agent")).toContain("little-coder");
    expect(headers.has("authorization")).toBe(false);
    const body = init.body ? JSON.parse(init.body) : undefined;
    if (body?.method === "initialize") return Response.json({ jsonrpc: "2.0", id: body.id,
      result: { protocolVersion: "2025-03-26", capabilities: { tools: {} }, serverInfo: { name: "fixture", version: "1" } } });
    if (body?.method !== "tools/call") return new Response(null, { status: body ? 202 : 405 });
    calls.push(body.params);
    const text = body.params.name === "web_search" ? "Node docs https://nodejs.org/api/" : "Extracted page: cancellation uses AbortSignal.";
    return Response.json({ jsonrpc: "2.0", id: body.id, result: { content: [{ type: "text", text }] } });
  }));
  const a = await createSession(), b = await createSession([], "custom-session-label-".repeat(10) + "end");
  for (const { session } of [a, b]) {
    script(session, (context, turn) => {
      const results = context.messages.filter((m: any) => m.role === "toolResult");
      if (turn === 0) return [{ type: "toolCall", id: "search", name: "websearch", arguments: { query: "node abort signal" } }];
      if (turn === 1) {
        const url = results.at(-1).content[0].text.match(/https:\/\/\S+/)[0];
        return [{ type: "toolCall", id: "fetch", name: "webfetch", arguments: { url } }];
      }
      expect(results.at(-1).content[0].text).toContain("cancellation uses AbortSignal");
      return [{ type: "text", text: "Read the cited Node documentation." }];
    });
  }
  await Promise.all([a.session.prompt("Find current Node documentation"), b.session.prompt("Find current Node documentation")]);
  expect(calls).toHaveLength(4);
  const defaultCalls = calls.filter((c) => c.arguments.session_id === a.manager.getSessionId());
  const customCalls = calls.filter((c) => c.arguments.session_id !== a.manager.getSessionId());
  expect(defaultCalls.map((c) => c.name)).toEqual(["web_search", "web_fetch"]);
  expect(customCalls.map((c) => c.name)).toEqual(["web_search", "web_fetch"]);
  expect(customCalls[0].arguments.session_id).toMatch(/^[0-9a-f-]{36}$/);
  expect(customCalls[0].arguments.session_id).toBe(customCalls[1].arguments.session_id);
  expect(JSON.stringify(calls)).not.toContain(b.manager.getSessionId());
  const metadata = b.manager.getEntries().find((entry) => entry.type === "custom" && entry.customType === "little-coder:parallel-session");
  expect(metadata?.type === "custom" && (metadata.data as any).id).toBe(customCalls[0].arguments.session_id);
});

it.each(["permission", "disabled"])("pi respects %s tool restrictions before making requests", async (mode) => {
  vi.stubEnv("LITTLE_CODER_WEB_PROVIDER", "parallel");
  vi.stubEnv("LITTLE_CODER_ALLOWED_TOOLS", mode === "permission" ? "read" : "webfetch,websearch");
  const fetcher = vi.fn();
  vi.stubGlobal("fetch", fetcher);
  const { session } = await createSession(mode === "disabled" ? ["websearch"] : []);
  script(session, (context, turn) => {
    if (turn === 0) return [{ type: "toolCall", id: "search", name: "websearch", arguments: { query: "node" } }];
    const result = context.messages.find((m: any) => m.role === "toolResult");
    expect(result.isError).toBe(true);
    expect(result.content[0].text).toMatch(mode === "permission" ? /not in _allowed_tools/ : /not found|unknown tool/i);
    return [{ type: "text", text: "Search is unavailable." }];
  });
  await session.prompt("Search the web");
  expect(fetcher).not.toHaveBeenCalled();
});
