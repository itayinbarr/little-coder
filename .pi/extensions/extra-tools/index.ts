import type { ExtensionAPI, ExtensionContext } from "@earendil-works/pi-coding-agent";
import { randomUUID } from "node:crypto";
import { Type } from "@sinclair/typebox";
import { globFiles, renderGlobOutcome } from "./glob.ts";

// Ports of tools.py::_glob, _webfetch, _websearch. Pi ships its own grep/find,
// so those are not re-registered here.

function webProvider(): "duckduckgo" | "parallel" {
  const provider = (process.env.LITTLE_CODER_WEB_PROVIDER ?? "").trim().toLowerCase();
  if (!provider || provider === "duckduckgo") return "duckduckgo";
  if (provider === "parallel") return "parallel";
  throw new Error("LITTLE_CODER_WEB_PROVIDER must be duckduckgo or parallel");
}

function webSignal(signal?: AbortSignal): AbortSignal {
  const timeout = AbortSignal.timeout(30_000);
  return signal ? AbortSignal.any([signal, timeout]) : timeout;
}

const opaqueUuid = /^[\da-f]{8}-[\da-f]{4}-[47][\da-f]{3}-[89ab][\da-f]{3}-[\da-f]{12}$/i;
const sessionEntryType = "little-coder:parallel-session";

export default function (pi: ExtensionAPI) {
  const customSessionIds = new WeakMap<object, string>();
  function parallelSessionId(ctx: ExtensionContext): string {
    const header = ctx.sessionManager.getHeader();
    if (!header) throw new Error("Cannot identify the current pi session");
    // pi's default UUID survives resumes. Custom --session-id labels can contain
    // personal text or exceed the MCP limit, so give those headers opaque IDs.
    if (opaqueUuid.test(header.id)) return header.id;
    let id = customSessionIds.get(header);
    if (!id) {
      // Read the whole session tree so compaction/branch navigation cannot lose
      // the ID. Forks copy entries, so only reuse metadata owned by this header.
      for (const entry of ctx.sessionManager.getEntries()) {
        if (entry.type !== "custom" || entry.customType !== sessionEntryType) continue;
        const saved = entry.data as { sessionId?: string; timestamp?: string; id?: string } | undefined;
        if (saved?.sessionId === header.id && saved.timestamp === header.timestamp &&
            typeof saved.id === "string" && opaqueUuid.test(saved.id)) {
          id = saved.id;
          break;
        }
      }
      if (!id) {
        id = randomUUID();
        pi.appendEntry(sessionEntryType, { sessionId: header.id, timestamp: header.timestamp, id });
      }
      customSessionIds.set(header, id);
    }
    return id;
  }

  // ── glob ────────────────────────────────────────────────────────────────
  pi.registerTool({
    name: "glob",
    label: "Glob",
    description:
      "Find files matching a glob pattern. Returns a sorted list of matching paths (up to 100). " +
      "Common dependency/build/cache dirs (node_modules, .git, dist, …) are skipped, and the walk " +
      "is bounded — for a focused search, pass a `path` rather than globbing a whole home directory.",
    parameters: Type.Object({
      pattern: Type.String({ description: "Glob pattern e.g. **/*.py" }),
      path: Type.Optional(Type.String({ description: "Base directory (default: cwd)" })),
    }),
    async execute(_id, { pattern, path }) {
      try {
        const base = path || process.cwd();
        // Bounded walk: prunes heavy dirs and caps total entries scanned so a
        // recursive glob from a huge root can't exhaust the process heap.
        const outcome = await globFiles(pattern, { base });
        return {
          content: [{ type: "text", text: renderGlobOutcome(outcome) }],
          details: {},
        };
      } catch (e) {
        return {
          content: [{ type: "text", text: `Error: ${(e as Error).message}` }],
          details: {},
          isError: true,
        };
      }
    },
  });

  // ── webfetch ────────────────────────────────────────────────────────────
  pi.registerTool({
    name: "webfetch",
    label: "WebFetch",
    description: process.env.LITTLE_CODER_WEB_PROVIDER?.trim().toLowerCase() === "parallel"
      ? "Fetch a URL via Parallel and return extracted Markdown excerpts. Capped at 25K chars."
      : "Fetch a URL and return its text content (HTML stripped). Capped at 25K chars.",
    parameters: Type.Object({
      url: Type.String({ description: "URL to fetch" }),
      prompt: Type.Optional(Type.String({ description: "Hint for what to extract (used by Parallel, up to 200 characters)" })),
    }),
    async execute(_id, { url, prompt }, signal, _update, ctx) {
      try {
        const requestSignal = webSignal(signal);
        if (webProvider() === "parallel") {
          if (!["http:", "https:"].includes(new URL(url).protocol)) {
            throw new Error("Parallel webfetch requires an HTTP or HTTPS URL");
          }
          const { parallelTool } = await import("./parallel.ts");
          requestSignal.throwIfAborted();
          return await parallelTool("web_fetch", {
            urls: [url],
            ...(prompt ? { objective: prompt.slice(0, 200) } : {}),
          }, parallelSessionId(ctx), requestSignal);
        }
        const res = await fetch(url, {
          headers: { "User-Agent": "little-coder/0.1" },
          redirect: "follow",
          signal: requestSignal,
        });
        if (!res.ok) {
          return {
            content: [{ type: "text", text: `Error: HTTP ${res.status} ${res.statusText}` }],
            details: {},
            isError: true,
          };
        }
        const ct = res.headers.get("content-type") || "";
        let text = await res.text();
        if (ct.includes("html")) {
          text = text.replace(/<script[^>]*>[\s\S]*?<\/script>/gi, "");
          text = text.replace(/<style[^>]*>[\s\S]*?<\/style>/gi, "");
          text = text.replace(/<[^>]+>/g, " ");
          text = text.replace(/\s+/g, " ").trim();
        }
        if (text.length > 25_000) text = text.slice(0, 25_000);
        return { content: [{ type: "text", text }], details: {} };
      } catch (e) {
        return {
          content: [{ type: "text", text: `Error: ${(e as Error).message}` }],
          details: {},
          isError: true,
        };
      }
    },
  });

  // ── websearch ───────────────────────────────────────────────────────────
  pi.registerTool({
    name: "websearch",
    label: "WebSearch",
    description: process.env.LITTLE_CODER_WEB_PROVIDER?.trim().toLowerCase() === "parallel"
      ? "Search the web via Parallel and return source URLs and text excerpts."
      : "Search the web via DuckDuckGo and return the top ~8 results as Markdown.",
    parameters: Type.Object({
      query: Type.String({ description: "Search query" }),
    }),
    async execute(_id, { query }, signal, _update, ctx) {
      try {
        const requestSignal = webSignal(signal);
        if (webProvider() === "parallel") {
          const { parallelTool } = await import("./parallel.ts");
          requestSignal.throwIfAborted();
          return await parallelTool("web_search", {
            objective: query,
            search_queries: [query],
          }, parallelSessionId(ctx), requestSignal);
        }
        const url = `https://html.duckduckgo.com/html/?q=${encodeURIComponent(query)}`;
        const res = await fetch(url, {
          headers: { "User-Agent": "Mozilla/5.0 (compatible)" },
          redirect: "follow",
          signal: requestSignal,
        });
        const body = await res.text();
        const titleRe = /class="result__title"[^>]*>[\s\S]*?<a[^>]*href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/g;
        const snippetRe = /class="result__snippet"[^>]*>([\s\S]*?)<\/div>/g;
        const titles: Array<{ link: string; title: string }> = [];
        let m: RegExpExecArray | null;
        while ((m = titleRe.exec(body)) && titles.length < 8) {
          titles.push({ link: m[1], title: m[2].replace(/<[^>]+>/g, "").trim() });
        }
        const snippets: string[] = [];
        while ((m = snippetRe.exec(body)) && snippets.length < 8) {
          snippets.push(m[1].replace(/<[^>]+>/g, "").trim());
        }
        if (titles.length === 0) {
          return {
            content: [{ type: "text", text: "No results found" }],
            details: {},
          };
        }
        const out = titles
          .map((t, i) => `**${t.title}**\n${t.link}\n${snippets[i] ?? ""}`)
          .join("\n\n");
        return { content: [{ type: "text", text: out }], details: {} };
      } catch (e) {
        return {
          content: [{ type: "text", text: `Error: ${(e as Error).message}` }],
          details: {},
          isError: true,
        };
      }
    },
  });
}
