import type { ExtensionAPI } from "@mariozechner/pi-coding-agent";
import { Type } from "@sinclair/typebox";

// Port of local/tools/browser.py. Playwright-powered Browser* tools with
// per-session lazy Page launch, chunked Readability extract, history stack,
// graceful degradation when Playwright isn't installed.
//
// To enable: `npm install playwright && npx playwright install chromium`.
// Without those the tools register but return a clear error.

const CHUNK_SIZE = 2048;

// Inlined "Readability-lite": remove heavy structural nodes and collapse
// whitespace. Passed to page.evaluate as a real function (not a string) —
// Playwright silently returns undefined when given a string function literal
// like `"() => {...}"` because it evaluates to a function *value*, not an
// invocation. `document` is only defined in the page context.
function readablePageText(): string {
  const doc = (globalThis as any).document;
  const clone = doc.body.cloneNode(true);
  const drop = clone.querySelectorAll(
    "script, style, noscript, iframe, nav, header, footer, aside, form",
  );
  drop.forEach((n: any) => n.remove());
  const text = (clone.innerText || "").replace(/\n{3,}/g, "\n\n").trim();
  return text;
}
function fallbackPageText(): string {
  const doc = (globalThis as any).document;
  return doc.body ? doc.body.innerText : "";
}

interface BrowserSession {
  pw: any;
  browser: any;
  context: any;
  page: any;
  history: string[];
  extractCache: Map<string, string>;
  error: string;
}

const sessions = new Map<string, BrowserSession>();

function sessionKey(): string {
  return process.env.LITTLE_CODER_SESSION_ID || "default";
}

function headful(): boolean {
  return !!process.env.BROWSER_HEADFUL;
}

async function ensureSession(): Promise<BrowserSession> {
  const key = sessionKey();
  let sess = sessions.get(key);
  if (!sess) {
    sess = {
      pw: null, browser: null, context: null, page: null,
      history: [], extractCache: new Map(), error: "",
    };
    sessions.set(key, sess);
  }
  if (sess.page || sess.error) return sess;
  try {
    // Optional runtime dep; cast avoids requiring @types/playwright at build time
    const playwright: any = await import("playwright" as any);
    const browser = await playwright.chromium.launch({ headless: !headful() });
    const context = await browser.newContext({
      userAgent: "Mozilla/5.0 (little-coder research agent)",
      viewport: { width: 1280, height: 900 },
    });
    const page = await context.newPage();
    page.setDefaultTimeout(20_000);
    sess.pw = playwright;
    sess.browser = browser;
    sess.context = context;
    sess.page = page;
  } catch (e: any) {
    if (e?.code === "ERR_MODULE_NOT_FOUND" || /Cannot find module 'playwright'/.test(e?.message ?? "")) {
      sess.error = "Playwright is not installed. Run: npm install playwright && npx playwright install chromium";
    } else {
      sess.error = `Browser launch failed: ${e?.message ?? e}`;
    }
  }
  return sess;
}

export async function resetBrowserSession(sessionId?: string): Promise<void> {
  const key = sessionId ?? sessionKey();
  const sess = sessions.get(key);
  if (!sess) return;
  sessions.delete(key);
  try { if (sess.page) await sess.page.close(); } catch {}
  try { if (sess.context) await sess.context.close(); } catch {}
  try { if (sess.browser) await sess.browser.close(); } catch {}
}

function errorResult(text: string) {
  return { content: [{ type: "text" as const, text }], details: {}, isError: true };
}
function textResult(text: string) {
  return { content: [{ type: "text" as const, text }], details: {} };
}

export default function (pi: ExtensionAPI) {
  pi.on("session_shutdown", async () => {
    await resetBrowserSession();
  });

  // ── BrowserNavigate ──────────────────────────────────────────────────
  pi.registerTool({
    name: "BrowserNavigate",
    label: "BrowserNavigate",
    description: "Navigate the browser to a URL. Must start with http:// or https://.",
    parameters: Type.Object({
      url: Type.String({ description: "URL to navigate to" }),
    }),
    async execute(_id, { url }) {
      const u = (url ?? "").trim();
      if (!u) return errorResult("Error: url is required");
      if (!u.startsWith("http://") && !u.startsWith("https://")) {
        return errorResult("Error: url must start with http:// or https://");
      }
      const sess = await ensureSession();
      if (sess.error) return errorResult(`Error: ${sess.error}`);
      try {
        const resp = await sess.page.goto(u, { waitUntil: "domcontentloaded" });
        sess.history.push(sess.page.url());
        sess.extractCache.clear();
        const status = resp ? resp.status() : "?";
        const title = await sess.page.title();
        return textResult(`[status=${status}] ${sess.page.url()}\ntitle: ${title}`);
      } catch (e: any) {
        return errorResult(`Error navigating to ${u}: ${e?.message ?? e}`);
      }
    },
  });

  // ── BrowserClick ─────────────────────────────────────────────────────
  pi.registerTool({
    name: "BrowserClick",
    label: "BrowserClick",
    description: "Click an element by CSS selector, or by ARIA role (with optional accessible name).",
    parameters: Type.Object({
      selector: Type.Optional(Type.String({ description: "CSS selector" })),
      role: Type.Optional(Type.String({ description: "ARIA role (e.g. button, link)" })),
      name: Type.Optional(Type.String({ description: "Accessible name for role" })),
    }),
    async execute(_id, { selector, role, name }) {
      const sel = (selector ?? "").trim();
      const r = (role ?? "").trim();
      const n = (name ?? "").trim();
      if (!sel && !r) {
        return errorResult("Error: provide either 'selector' or 'role' (+ optional 'name')");
      }
      const sess = await ensureSession();
      if (sess.error) return errorResult(`Error: ${sess.error}`);
      try {
        const loc = r
          ? (n ? sess.page.getByRole(r, { name: n }) : sess.page.getByRole(r))
          : sess.page.locator(sel);
        await loc.first().click();
        await sess.page.waitForLoadState("domcontentloaded", { timeout: 10_000 });
        sess.history.push(sess.page.url());
        sess.extractCache.clear();
        return textResult(`clicked. url=${sess.page.url()}`);
      } catch (e: any) {
        return errorResult(`Error clicking: ${e?.message ?? e}`);
      }
    },
  });

  // ── BrowserType ──────────────────────────────────────────────────────
  pi.registerTool({
    name: "BrowserType",
    label: "BrowserType",
    description: "Fill a form field by selector. Optionally submit by pressing Enter.",
    parameters: Type.Object({
      selector: Type.String({ description: "CSS selector of the input" }),
      text: Type.String({ description: "Text to type" }),
      submit: Type.Optional(Type.Boolean({ description: "Press Enter after typing" })),
    }),
    async execute(_id, { selector, text, submit }) {
      const sel = (selector ?? "").trim();
      const t = text ?? "";
      if (!sel) return errorResult("Error: selector is required");
      const sess = await ensureSession();
      if (sess.error) return errorResult(`Error: ${sess.error}`);
      try {
        await sess.page.fill(sel, t);
        if (submit) {
          await sess.page.press(sel, "Enter");
          await sess.page.waitForLoadState("domcontentloaded", { timeout: 10_000 });
          sess.history.push(sess.page.url());
          sess.extractCache.clear();
        }
        return textResult(`typed ${t.length} chars into ${sel}${submit ? " + Enter" : ""}`);
      } catch (e: any) {
        return errorResult(`Error typing: ${e?.message ?? e}`);
      }
    },
  });

  // ── BrowserScroll ────────────────────────────────────────────────────
  pi.registerTool({
    name: "BrowserScroll",
    label: "BrowserScroll",
    description: "Scroll the current page up or down by a pixel amount (default 800px down).",
    parameters: Type.Object({
      direction: Type.Optional(Type.String({ description: "up or down" })),
      amount: Type.Optional(Type.Integer({ description: "Pixels (default 800)" })),
    }),
    async execute(_id, { direction, amount }) {
      const dir = ((direction ?? "down") as string).toLowerCase();
      const amt = typeof amount === "number" ? amount : 800;
      const sess = await ensureSession();
      if (sess.error) return errorResult(`Error: ${sess.error}`);
      const dy = dir === "down" ? amt : -amt;
      try {
        await sess.page.evaluate(`window.scrollBy(0, ${dy})`);
        return textResult(`scrolled ${dir} by ${amt}px`);
      } catch (e: any) {
        return errorResult(`Error scrolling: ${e?.message ?? e}`);
      }
    },
  });

  // ── BrowserExtract ───────────────────────────────────────────────────
  pi.registerTool({
    name: "BrowserExtract",
    label: "BrowserExtract",
    description:
      "Extract the current page's readable text. Returns a 2KB chunk with cursor+has_more " +
      "so one page can't swamp context. Call repeatedly with the last 'next=' cursor.",
    parameters: Type.Object({
      cursor: Type.Optional(Type.String({ description: "Byte offset to start from (default 0)" })),
    }),
    async execute(_id, { cursor }) {
      const sess = await ensureSession();
      if (sess.error) return errorResult(`Error: ${sess.error}`);
      try {
        if (!sess.extractCache.has("full")) {
          let text: string = await sess.page.evaluate(readablePageText);
          if (!text) {
            text = await sess.page.evaluate(fallbackPageText);
          }
          sess.extractCache.set("full", text ?? "");
        }
        const full = sess.extractCache.get("full") ?? "";
        const startRaw = parseInt((cursor ?? "0") as string, 10);
        const start = Number.isFinite(startRaw) ? startRaw : 0;
        if (start < 0 || start >= full.length) {
          return textResult(`[cursor=${start} past end (length=${full.length})]`);
        }
        const end = Math.min(start + CHUNK_SIZE, full.length);
        const chunk = full.slice(start, end);
        const hasMore = end < full.length;
        const footerBits = [
          `cursor=${start}`,
          `next=${hasMore ? end : "null"}`,
          `total=${full.length}`,
        ];
        if (hasMore) footerBits.push("has_more=true");
        return textResult(`${chunk}\n[${footerBits.join(" ")}]`);
      } catch (e: any) {
        return errorResult(`Error extracting: ${e?.message ?? e}`);
      }
    },
  });

  // ── BrowserBack ──────────────────────────────────────────────────────
  pi.registerTool({
    name: "BrowserBack",
    label: "BrowserBack",
    description: "Navigate back in the browser's history.",
    parameters: Type.Object({}),
    async execute() {
      const sess = await ensureSession();
      if (sess.error) return errorResult(`Error: ${sess.error}`);
      try {
        await sess.page.goBack({ waitUntil: "domcontentloaded" });
        sess.extractCache.clear();
        return textResult(`back. url=${sess.page.url()}`);
      } catch (e: any) {
        return errorResult(`Error going back: ${e?.message ?? e}`);
      }
    },
  });

  // ── BrowserHistory ───────────────────────────────────────────────────
  pi.registerTool({
    name: "BrowserHistory",
    label: "BrowserHistory",
    description: "List the last 20 URLs visited in this session.",
    parameters: Type.Object({}),
    async execute() {
      const sess = await ensureSession();
      if (sess.error) return errorResult(`Error: ${sess.error}`);
      if (sess.history.length === 0) return textResult("(no pages visited yet)");
      const lines = sess.history.slice(-20).map((u, i) => `${i + 1}. ${u}`);
      return textResult(lines.join("\n"));
    },
  });
}
