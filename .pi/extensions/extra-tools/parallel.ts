import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StreamableHTTPClientTransport } from "@modelcontextprotocol/sdk/client/streamableHttp.js";

const endpoint = "https://search.parallel.ai/mcp";
const userAgent = "little-coder (https://github.com/itayinbarr/little-coder)";

// Each call owns its transport, while the caller supplies pi's conversation UUID.
// A connection or extension instance must never own the conversation identity.
export async function parallelTool(
  name: "web_search" | "web_fetch",
  args: Record<string, unknown>,
  sessionId: string,
  signal: AbortSignal,
) {
  signal.throwIfAborted();
  const client = new Client({ name: "little-coder", version: "1" });
  const transport = new StreamableHTTPClientTransport(new URL(endpoint), {
    fetch: (input, init) => {
      const headers = new Headers(init?.headers);
      headers.set("User-Agent", userAgent);
      return fetch(input, {
        ...init,
        headers,
        signal: init?.signal ? AbortSignal.any([signal, init.signal]) : signal,
      });
    },
  });
  try {
    await client.connect(transport);
    const result = await client.callTool(
      { name, arguments: { ...args, session_id: sessionId } },
      undefined,
      { signal, timeout: 30_000 },
    );
    const text = (result.content as Array<{ type: string; text?: string }>)
      .filter((item) => item.type === "text" && typeof item.text === "string")
      .map((item) => item.text)
      .join("\n\n");
    if (!text) throw new Error("Parallel returned no text content");
    return {
      content: [{ type: "text" as const, text: text.slice(0, 25_000) }],
      details: {},
      ...(result.isError ? { isError: true } : {}),
    };
  } finally {
    await client.close();
  }
}
