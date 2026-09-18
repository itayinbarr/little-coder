import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "@sinclair/typebox";
import {
  subCoderAccess,
  runSubCoder,
  runSubCodersConcurrent,
  truncateReport,
  type SubCoderItem,
  type SubCoderResult,
} from "./spawn.ts";
import { SubCoderTracker } from "./tracker.ts";

// The `dispatch` tool: the main little-coder spawns isolated child little-coder
// sessions ("sub-coders") to research a focused question — they read the repo
// and browse online, then return a CONCISE report. The full child transcript
// lives in the tool's `details` (UI-only); only the short report enters the
// parent model's context. A live panel above the input tracks them while they
// run. See spawn.ts for the engine and the read-only constraints.

const MAX_PARALLEL = 4;

/** "provider/id" of the current model, so children run on the same backend. */
export function currentModelId(ctx: any): string | undefined {
  const m = ctx?.model;
  if (!m || typeof m.id !== "string") return undefined;
  return m.provider ? `${m.provider}/${m.id}` : m.id;
}

/** A short label for a single-mode task (first few words). */
function shortLabel(task: string): string {
  const words = task.trim().split(/\s+/).filter(Boolean).slice(0, 4).join(" ");
  return words.length > 28 ? `${words.slice(0, 27)}…` : words || "sub-coder";
}

function buildContent(results: SubCoderResult[]): string {
  if (results.length === 1) {
    const r = results[0];
    if (r.exitCode !== 0) return `Sub-coder "${r.label}" ${r.stopReason || "failed"}: ${r.errorMessage || "(no output)"}`;
    return truncateReport(r.report) || "(no report)";
  }
  const ok = results.filter((r) => r.exitCode === 0).length;
  const blocks = results.map((r) => {
    const status = r.exitCode === 0 ? "" : ` [${r.stopReason || "failed"}]`;
    const body = r.exitCode === 0 ? truncateReport(r.report) : r.errorMessage || "(no output)";
    return `### ${r.label}${status}\n${body || "(no report)"}`;
  });
  return `${ok}/${results.length} sub-coders succeeded.\n\n${blocks.join("\n\n")}`;
}

export default function (pi: ExtensionAPI) {
  pi.registerTool({
    name: "dispatch",
    label: "Dispatch sub-coder",
    // The description has to state the child's actual powers, not the default
    // ones: a model told children "CANNOT edit or write files" will not
    // delegate work that needs an edit, even when the user has enabled it
    // (issue #93).
    description: [
      "Dispatch one or more isolated sub-coders to research a focused question.",
      "Each runs in its own context window, can read the repo and browse online",
      "(read, grep, glob, webfetch, websearch, browser, read-only bash)",
      subCoderAccess() === "write"
        ? "and CAN edit and write files, but CANNOT dispatch further sub-coders."
        : "but CANNOT edit or write files.",
      "Each returns a concise report. Use this to gather",
      "information without cluttering your own context.",
      "Single: { task }. Parallel: { tasks: [{ label, task }] } (max 4).",
    ].join(" "),
    parameters: Type.Object({
      task: Type.Optional(Type.String({ description: "A single research task (single mode)" })),
      tasks: Type.Optional(
        Type.Array(
          Type.Object({
            label: Type.String({ description: "Short name for this sub-coder (shown in the tracker)" }),
            task: Type.String({ description: "The research task delegated to this sub-coder" }),
          }),
          { description: `Up to ${MAX_PARALLEL} tasks to run in parallel` },
        ),
      ),
      cwd: Type.Optional(Type.String({ description: "Working directory for the sub-coders (default: current)" })),
    }),

    async execute(_toolCallId, params, signal, onUpdate, ctx) {
      const hasSingle = typeof params.task === "string" && params.task.trim().length > 0;
      const hasTasks = Array.isArray(params.tasks) && params.tasks.length > 0;
      if (hasSingle === hasTasks) {
        return {
          content: [{ type: "text", text: "Provide exactly one of `task` (single) or `tasks` (parallel)." }],
          details: { results: [] },
          isError: true,
        };
      }
      if (hasTasks && params.tasks!.length > MAX_PARALLEL) {
        return {
          content: [{ type: "text", text: `Too many parallel tasks (${params.tasks!.length}). Max is ${MAX_PARALLEL}.` }],
          details: { results: [] },
          isError: true,
        };
      }

      const cwd = params.cwd || ctx.cwd;
      const items: SubCoderItem[] = hasSingle
        ? [{ id: "1", label: shortLabel(params.task!), task: params.task!, cwd }]
        : params.tasks!.map((t, i) => ({ id: String(i + 1), label: t.label, task: t.task, cwd }));

      const model = currentModelId(ctx);
      const tracker = new SubCoderTracker(ctx as any);
      tracker.begin(items.map((it) => ({ id: it.id, label: it.label })));

      const streamToToolCard = (results: SubCoderResult[]) => {
        if (!onUpdate) return;
        const done = results.filter((r) => r.exitCode !== -1).length;
        onUpdate({
          content: [{ type: "text", text: `${done}/${results.length} sub-coders done…` }],
          details: { results },
        });
      };

      let results: SubCoderResult[];
      try {
        if (hasSingle) {
          const r = await runSubCoder({
            ...items[0],
            model,
            signal,
            onUpdate: (live) => {
              tracker.update([live]);
              streamToToolCard([live]);
            },
          });
          results = [r];
        } else {
          results = await runSubCodersConcurrent(items, {
            model,
            signal,
            onUpdate: (all) => {
              tracker.update(all);
              streamToToolCard(all);
            },
          });
        }
      } finally {
        tracker.end();
      }

      const anyError = results.some((r) => r.exitCode !== 0);
      const allError = results.every((r) => r.exitCode !== 0);
      return {
        content: [{ type: "text", text: buildContent(results) }],
        details: { results },
        isError: allError && anyError,
      };
    },

    // Renderers return a duck-typed Component ({ render→lines, invalidate }).
    // pi 0.79 stopped hoisting pi-tui, so we build colored lines via `theme`
    // rather than importing pi-tui primitives (same approach as branding).
    renderCall(args: any, theme: any) {
      const lines: string[] = [];
      const title = theme.fg("toolTitle", theme.bold("dispatch "));
      if (Array.isArray(args.tasks) && args.tasks.length > 0) {
        lines.push(title + theme.fg("accent", `${args.tasks.length} sub-coders`));
        for (const t of args.tasks.slice(0, MAX_PARALLEL)) {
          const preview = t.task.length > 48 ? `${t.task.slice(0, 48)}…` : t.task;
          lines.push(`  ${theme.fg("accent", t.label)}${theme.fg("dim", ` — ${preview}`)}`);
        }
      } else {
        const task = String(args.task ?? "…");
        lines.push(title + theme.fg("dim", task.length > 64 ? `${task.slice(0, 64)}…` : task));
      }
      return makeComponent(lines);
    },

    renderResult(result: any, options: any, theme: any) {
      const expanded = !!options?.expanded;
      const results: SubCoderResult[] = result?.details?.results ?? [];
      if (results.length === 0) {
        const t = result?.content?.[0];
        return makeComponent([t?.type === "text" ? t.text : "(no output)"]);
      }
      const ok = results.filter((r) => r.exitCode === 0).length;
      const lines: string[] = [
        theme.fg("toolTitle", theme.bold("dispatch ")) + theme.fg("accent", `${ok}/${results.length} sub-coders`),
      ];
      for (const r of results) {
        const icon = r.exitCode === 0 ? theme.fg("success", "✓") : theme.fg("error", "✗");
        lines.push("");
        lines.push(`${icon} ${theme.fg("accent", r.label)}`);
        const body = r.exitCode === 0 ? r.report : r.errorMessage || r.stderr || "(no output)";
        const bodyLines = body.trim() ? body.trim().split("\n") : ["(no output)"];
        const shown = expanded ? bodyLines : bodyLines.slice(0, 4);
        for (const bl of shown) lines.push(theme.fg("toolOutput", bl));
        if (!expanded && bodyLines.length > shown.length) lines.push(theme.fg("muted", "  …"));
      }
      if (!expanded) lines.push(theme.fg("muted", "(Ctrl+O to expand)"));
      return makeComponent(lines);
    },
  });
}

/**
 * Sanitize and wrap lines for the dispatch tool-result panel.
 *
 * Two problems we solve:
 * 1. Long whitespace-free tokens (URLs, file paths, base64) are broken up
 *    so word-wrap has somewhere to split — follows openclaw-cn's
 *    tui-formatters.ts sanitizer (commit 8c822da).
 * 2. Each line is wrapped to the pi-supplied width so no rendered line
 *    exceeds the terminal — the failure mode of issues #48 / #51 (a 134-char
 *    sub-coder report sentence + pi's 1-char panel left margin overflowed
 *    pi-tui's strict line-width check, including on `--resume` because the
 *    same renderer paints session history).
 *
 * Word-wrap was contributed by @steverhoades in PR #49; v1.9.5 cherry-picked
 * it onto v1.9.4 because wrapping is a strictly better UX for markdown
 * report bodies than the truncate-with-ellipsis we shipped in v1.9.4 — the
 * user sees the whole sentence across multiple lines instead of a cut-off
 * tail. The 2-char safety margin (`width - 2`) survives wide-unicode chars
 * our char-count-based stripAnsi/length undercounts, and absorbs pi's panel
 * frame margin so the rendered output still fits.
 *
 * pi-tui's own visibleWidth / truncateToWidth aren't importable here (pi
 * 0.79 stopped hoisting pi-tui for extensions), so the ANSI-aware helpers
 * are inlined.
 */
const ANSI_RE = /\x1b\[[0-9;]*m/g;
const MAX_TOKEN_CHARS = 32;
const LONG_TOKEN_RE = /\S{33,}/g;

function chunkToken(token: string): string[] {
  const chunks: string[] = [];
  for (let i = 0; i < token.length; i += MAX_TOKEN_CHARS) {
    chunks.push(token.slice(i, i + MAX_TOKEN_CHARS));
  }
  return chunks;
}

function sanitizeLongTokens(text: string): string {
  return LONG_TOKEN_RE.test(text)
    ? text.replace(LONG_TOKEN_RE, (token) => chunkToken(token).join(" "))
    : text;
}

/** Extract leading ANSI SGR codes so wrapped lines can re-apply them. */
function extractAnsiPrefix(text: string): { prefix: string; rest: string } {
  let end = 0;
  while (end < text.length && text.slice(end, end + 2) === "\x1b[") {
    const mPos = text.indexOf("m", end + 2);
    if (mPos === -1) break;
    end = mPos + 1;
  }
  return { prefix: text.slice(0, end), rest: text.slice(end) };
}

function stripAnsi(text: string): string {
  return text.replace(ANSI_RE, "");
}

/** Word-wrap plain text at whitespace; assumes long tokens are pre-chunked. */
function wrapPlainText(text: string, maxWidth: number): string[] {
  if (text.length <= maxWidth) return [text];
  const words = text.split(/\s+/);
  const result: string[] = [];
  let current = "";
  for (const word of words) {
    if (!word) continue;
    if (current.length === 0) {
      current = word;
    } else if (current.length + 1 + word.length <= maxWidth) {
      current += " " + word;
    } else {
      result.push(current);
      current = word;
    }
  }
  if (current) result.push(current);
  return result.length > 0 ? result : [text];
}

/** Wrap one ANSI-aware line to width, re-applying any leading SGR prefix. */
function wrapLine(line: string, width: number): string[] {
  const plain = stripAnsi(line);
  if (plain.length <= width) return [line];
  const { prefix } = extractAnsiPrefix(line);
  const wrappedLines = wrapPlainText(plain, width);
  return wrappedLines.map((l) => prefix + l);
}

export function makeComponent(lines: string[]) {
  return {
    render(width: number): string[] {
      const cap = Math.max(1, width - 2);
      const output: string[] = [];
      for (const line of lines) {
        const sanitized = sanitizeLongTokens(line);
        for (const wrapped of wrapLine(sanitized, cap)) {
          output.push(wrapped);
        }
      }
      return output;
    },
    invalidate() {},
  };
}
