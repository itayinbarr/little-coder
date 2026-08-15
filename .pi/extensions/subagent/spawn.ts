// Sub-coder spawn engine.
//
// A "sub-coder" is a child little-coder session with an isolated context window,
// spawned to research a focused question (read the repo + browse online) and
// report back concisely. Both the `dispatch` tool (index.ts) and Plan Mode
// (../plan-mode) drive children through this module.
//
// Why spawn little-coder's OWN launcher and not bare `pi`: the child must use
// the same local-model provider, the same extensions, and the same AGENTS.md as
// the parent. The launcher (bin/little-coder.mjs) is what composes all of that —
// it registers the provider (llama-cpp-provider), wires every .pi/extension, and
// passes --system-prompt AGENTS.md. Spawning `pi` directly would yield a blank
// agent with none of it. We therefore re-invoke the launcher headless
// (--mode json -p --no-session) and parse pi's JSON event stream from stdout.
//
// The child is constrained to read + browse (no edit/write, no recursive
// dispatch) entirely through environment variables the existing gates already
// honor — see buildChildEnv().

import { spawn, type ChildProcess } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

/**
 * Escalate to SIGKILL `delayMs` after a SIGTERM, unless the child has already
 * exited. The gate is the caller's `hasExited()` — deliberately NOT
 * `proc.killed`, which Node sets true on signal *dispatch* (not on actual
 * termination), which made the previous `if (!proc.killed)` escalation
 * unreachable and let a SIGTERM-ignoring child leak as an orphan. Returns the
 * timer so callers may clear it. Never throws (the process may already be gone).
 */
export function scheduleForceKill(
  proc: Pick<ChildProcess, "kill">,
  hasExited: () => boolean,
  delayMs = 4000,
): ReturnType<typeof setTimeout> {
  return setTimeout(() => {
    try {
      if (!hasExited()) proc.kill("SIGKILL");
    } catch {
      /* ignore */
    }
  }, delayMs);
}

// Tools a sub-coder may use: read + search + browse online + read-only bash.
// Enforced by the tool-gating extension in the child. Deliberately omits
// edit/write (children never mutate the tree) and `dispatch` (no fan-out bombs).
export const SUBCODER_ALLOWED_TOOLS = [
  "read",
  "grep",
  "glob",
  "find",
  "ls",
  "bash",
  "webfetch",
  "websearch",
  "BrowserNavigate",
  "BrowserClick",
  "BrowserType",
  "BrowserScroll",
  "BrowserExtract",
  "BrowserBack",
  "BrowserHistory",
].join(",");

// Appended to every task so children answer with a short, parent-friendly
// report rather than a wall of pasted file contents.
export const REPORT_SUFFIX =
  "\n\nWhen done, reply with a CONCISE report (≤ ~200 words): the key findings, " +
  "file:line citations where relevant, and a direct answer to the task. Do NOT " +
  "paste large file contents or long logs — summarize them.";

export const MAX_REPORT_CHARS = 2000;

export interface SubCoderUsage {
  input: number;
  output: number;
  cost: number;
  turns: number;
  contextTokens: number;
}

export interface SubCoderResult {
  id: string;
  label: string;
  task: string;
  /** -1 = still running, 0 = ok, >0 = failed. */
  exitCode: number;
  /** The child's final assistant text — the report shown to the parent model. */
  report: string;
  /** Full child transcript. UI-only (rendered in tool details); never sent to the parent model. */
  messages: any[];
  stderr: string;
  usage: SubCoderUsage;
  stopReason?: string;
  errorMessage?: string;
}

function emptyUsage(): SubCoderUsage {
  return { input: 0, output: 0, cost: 0, turns: 0, contextTokens: 0 };
}

// .pi/extensions/subagent/spawn.ts → up 3 → package root → bin/little-coder.mjs.
// Same path math as branding/index.ts; works in the local checkout and the
// installed npm layout.
export function resolveLauncher(): string {
  const here = dirname(fileURLToPath(import.meta.url));
  return resolve(here, "..", "..", "..", "bin", "little-coder.mjs");
}

export function buildChildEnv(extra?: Record<string, string>): NodeJS.ProcessEnv {
  return {
    ...process.env,
    // Constrain the child to read + browse, no mutation, no recursion.
    LITTLE_CODER_ALLOWED_TOOLS: SUBCODER_ALLOWED_TOOLS,
    // bash limited to permission-gate's read-only BUILTIN_SAFE_PREFIXES.
    LITTLE_CODER_PERMISSION_MODE: "auto",
    // Headless fast-path in the launcher (skip update-check + settings write).
    LITTLE_CODER_SUBAGENT: "1",
    // Belt and suspenders: never show pi's update banner in a child.
    PI_SKIP_VERSION_CHECK: "1",
    ...extra,
  };
}

export function defaultConcurrency(): number {
  // Default to 1 (fully serial). On small local setups two concurrent
  // sub-coders contend for the same single-GPU/CPU model server and run
  // *slower* than one at a time (issue #57, reported independently by two
  // users). Parallelism is opt-in via LITTLE_CODER_SUBCODER_CONCURRENCY.
  //
  // Any explicit value is clamped to a floor of 1: a user who sets `=0`
  // (or a negative) means "don't parallelize" — serial — not "fall back to
  // the default", which is what the old `n > 0` test silently did. Both the
  // normal dispatch tool and plan-mode go through this single function, so
  // the env var now governs plan-mode research fan-out too.
  const raw = process.env.LITTLE_CODER_SUBCODER_CONCURRENCY;
  if (raw === undefined || raw === "") return 1;
  const n = Number(raw);
  if (!Number.isFinite(n)) return 1;
  return Math.max(1, Math.floor(n));
}

/** The last assistant text block in a transcript — the child's report. */
export function getFinalText(messages: any[]): string {
  for (let i = messages.length - 1; i >= 0; i--) {
    const m = messages[i];
    if (m?.role === "assistant" && Array.isArray(m.content)) {
      for (const part of m.content) {
        if (part?.type === "text" && typeof part.text === "string" && part.text.trim()) {
          return part.text;
        }
      }
    }
  }
  return "";
}

export function truncateReport(text: string, max = MAX_REPORT_CHARS): string {
  const t = (text ?? "").trim();
  if (t.length <= max) return t;
  return `${t.slice(0, max).trimEnd()}\n\n… (report truncated at ${max} chars — full transcript in tool details)`;
}

/** A one-line "what is this child doing right now" string for the tracker. */
export function summarizeActivity(r: SubCoderResult): string {
  const cap = (s: string, n = 56): string => (s.length > n ? `${s.slice(0, n - 1)}…` : s);
  if (r.exitCode === 0) {
    const firstLine = r.report.split(/\r?\n/).find((l) => l.trim()) ?? "(done)";
    return cap(firstLine);
  }
  if (r.exitCode > 0) {
    // The error path used to return raw errorMessage / stderr UNCAPPED, which
    // routinely runs ~200 chars (a child process error with a URL + stack
    // fragment). The tracker passes that straight into a widget line, and any
    // line wider than the terminal crashes pi-tui (issue #48). Cap here so the
    // source string is bounded; the widget also truncates the assembled row
    // for defense in depth.
    return cap(r.errorMessage || r.stderr.split(/\r?\n/)[0] || "(failed)");
  }
  // running: surface the most recent tool call, else the latest partial text.
  for (let i = r.messages.length - 1; i >= 0; i--) {
    const m = r.messages[i];
    if (m?.role === "assistant" && Array.isArray(m.content)) {
      for (let j = m.content.length - 1; j >= 0; j--) {
        const part = m.content[j];
        if (part?.type === "toolCall") {
          const a = part.arguments ?? {};
          const hint = a.pattern || a.query || a.url || a.path || a.file_path || a.command || "";
          return cap(`→ ${part.name}${hint ? ` ${String(hint).slice(0, 40)}` : ""}`);
        }
      }
    }
  }
  return "working…";
}

export interface RunSubCoderOptions {
  id: string;
  label: string;
  task: string;
  cwd: string;
  /** "provider/id" of the parent's model, so the child uses the same one. */
  model?: string;
  signal?: AbortSignal;
  /** Called whenever the child emits a new message, with the live result. */
  onUpdate?: (r: SubCoderResult) => void;
  /**
   * Text appended to the task. Defaults to REPORT_SUFFIX (ask for a concise,
   * citation-bearing research report) — right for research children. Pass "" for
   * REASONING steps (e.g. "output ONLY JSON" / "write a brief"), where the report
   * framing derails the model into answering the topic instead of the instruction.
   */
  reportSuffix?: string;
  /**
   * Override the child's allowed tools (default SUBCODER_ALLOWED_TOOLS). Use a
   * narrower set to, e.g., deny `bash` to research children so they can't
   * scaffold/compile in the working tree, or restrict reasoning steps to
   * read-only local tools. A comma-separated tool-name string.
   */
  allowedTools?: string;
  /**
   * Watchdog: kill the child and mark it failed if it runs longer than this many
   * ms. Guards against a hung agent (e.g. a browser stuck on a page) blocking the
   * whole run indefinitely. Omit for no timeout.
   */
  timeoutMs?: number;
  /**
   * If the child is killed by the watchdog (only), run it ONCE more with a fresh
   * timeout window before giving up. A hang is often transient (a single browser
   * page wedged, a slow source) and a clean retry recovers the finding — otherwise
   * that subtopic is silently missing from the report. Only timeouts are retried;
   * a deterministic failure (bad launcher, non-zero exit) is returned as-is.
   */
  retryOnTimeout?: boolean;
}

// Did the watchdog (not a normal exit) kill this child?
function wasTimeout(r: SubCoderResult): boolean {
  return r.exitCode !== 0 && /timed out/i.test(r.errorMessage ?? "");
}

/**
 * Run one sub-coder, retrying once if the watchdog killed it and retryOnTimeout is
 * set. Never throws — failures land in exitCode/stderr.
 */
export async function runSubCoder(opts: RunSubCoderOptions): Promise<SubCoderResult> {
  const first = await runSubCoderOnce(opts);
  if (!opts.retryOnTimeout || !wasTimeout(first) || opts.signal?.aborted) return first;
  const second = await runSubCoderOnce(opts);
  // Record that a retry happened (visible in tool details, never sent to the parent).
  second.stderr =
    `[retry] first attempt ${first.errorMessage}; retried once` +
    `${second.exitCode === 0 ? " — succeeded" : ""}\n${second.stderr}`;
  return second;
}

/** Run one sub-coder to completion. Never throws — failures land in exitCode/stderr. */
async function runSubCoderOnce(opts: RunSubCoderOptions): Promise<SubCoderResult> {
  const result: SubCoderResult = {
    id: opts.id,
    label: opts.label,
    task: opts.task,
    exitCode: -1,
    report: "",
    messages: [],
    stderr: "",
    usage: emptyUsage(),
  };

  const launcher = resolveLauncher();
  if (!existsSync(launcher)) {
    result.exitCode = 1;
    result.stderr = `sub-coder launcher not found at ${launcher}`;
    result.errorMessage = result.stderr;
    opts.onUpdate?.(result);
    return result;
  }

  const args = [
    launcher,
    "--no-update-check",
    "--mode",
    "json",
    "-p",
    "--no-session",
    // Match the parent's model so children run on the same backend. Without
    // this the child would fall back to pi's default model.
    ...(opts.model ? ["--model", opts.model] : []),
    opts.task + (opts.reportSuffix ?? REPORT_SUFFIX),
  ];

  const emit = () => {
    result.report = getFinalText(result.messages);
    opts.onUpdate?.(result);
  };

  const exitCode = await new Promise<number>((resolveP) => {
    let proc;
    try {
      proc = spawn(process.execPath, args, {
        cwd: opts.cwd,
        shell: false,
        stdio: ["ignore", "pipe", "pipe"],
        env: buildChildEnv(opts.allowedTools ? { LITTLE_CODER_ALLOWED_TOOLS: opts.allowedTools } : undefined),
      });
    } catch (e) {
      result.stderr += String((e as Error)?.message ?? e);
      resolveP(1);
      return;
    }

    let buffer = "";
    const processLine = (line: string) => {
      if (!line.trim()) return;
      let ev: any;
      try {
        ev = JSON.parse(line);
      } catch {
        return; // non-JSON noise (shouldn't happen in --mode json, but be safe)
      }
      if (ev.type === "message_end" && ev.message) {
        const msg = ev.message;
        result.messages.push(msg);
        if (msg.role === "assistant") {
          result.usage.turns++;
          const u = msg.usage;
          if (u) {
            result.usage.input += u.input || 0;
            result.usage.output += u.output || 0;
            result.usage.cost += u.cost?.total || 0;
            result.usage.contextTokens = u.totalTokens || 0;
          }
          if (msg.stopReason) result.stopReason = msg.stopReason;
          if (msg.errorMessage) result.errorMessage = msg.errorMessage;
        }
        emit();
      } else if (ev.type === "tool_result_end" && ev.message) {
        result.messages.push(ev.message);
        emit();
      }
    };

    proc.stdout.on("data", (d) => {
      buffer += d.toString();
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";
      for (const l of lines) processLine(l);
    });
    proc.stderr.on("data", (d) => {
      result.stderr += d.toString();
    });
    // Tracks whether the child has actually exited. proc.killed is NOT this: Node
    // sets proc.killed true the instant a signal is *dispatched*, not when the
    // process dies, so gating the SIGKILL escalation on !proc.killed made it
    // unreachable — a child that ignores SIGTERM was never force-killed and
    // leaked as an orphan. The close/error handlers below flip this true.
    let exited = false;
    // SIGTERM then SIGKILL — shared by the abort-signal and the watchdog timeout.
    const kill = () => {
      try {
        proc.kill("SIGTERM");
      } catch {
        /* already gone */
      }
      scheduleForceKill(proc, () => exited);
    };

    // Watchdog: a child that hangs (e.g. a browser stuck on a page) must not
    // block the run forever. On timeout, mark it failed and kill it.
    let watchdog: ReturnType<typeof setTimeout> | null = null;
    if (opts.timeoutMs && opts.timeoutMs > 0) {
      watchdog = setTimeout(() => {
        result.errorMessage = `timed out after ${Math.round(opts.timeoutMs! / 1000)}s`;
        result.stderr += `\n[watchdog] ${result.errorMessage}`;
        kill();
      }, opts.timeoutMs);
    }

    proc.on("close", (code) => {
      exited = true;
      if (watchdog) clearTimeout(watchdog);
      if (buffer.trim()) processLine(buffer);
      resolveP(code ?? 0);
    });
    proc.on("error", (e) => {
      exited = true;
      if (watchdog) clearTimeout(watchdog);
      result.stderr += String(e?.message ?? e);
      resolveP(1);
    });

    if (opts.signal) {
      if (opts.signal.aborted) kill();
      else opts.signal.addEventListener("abort", kill, { once: true });
    }
  });

  result.exitCode = exitCode;
  result.report = getFinalText(result.messages);
  if (exitCode !== 0 && !result.errorMessage) {
    result.errorMessage = result.stderr.split(/\r?\n/).filter(Boolean).slice(-1)[0] || `exited ${exitCode}`;
  }
  return result;
}

export interface SubCoderItem {
  id: string;
  label: string;
  task: string;
  cwd: string;
}

async function mapWithConcurrencyLimit<TIn, TOut>(
  items: TIn[],
  concurrency: number,
  fn: (item: TIn, index: number) => Promise<TOut>,
): Promise<TOut[]> {
  if (items.length === 0) return [];
  const limit = Math.max(1, Math.min(concurrency, items.length));
  const results: TOut[] = new Array(items.length);
  let next = 0;
  const workers = new Array(limit).fill(null).map(async () => {
    while (true) {
      const cur = next++;
      if (cur >= items.length) return;
      results[cur] = await fn(items[cur], cur);
    }
  });
  await Promise.all(workers);
  return results;
}

/**
 * Run several sub-coders with a concurrency cap (default 1 — serial; a single
 * local backend is easily starved, see defaultConcurrency). `onUpdate` receives a fresh snapshot of all
 * results whenever any child changes, which drives the live tracker.
 */
export async function runSubCodersConcurrent(
  items: SubCoderItem[],
  opts: {
    signal?: AbortSignal;
    concurrency?: number;
    model?: string;
    allowedTools?: string;
    timeoutMs?: number;
    retryOnTimeout?: boolean;
    reportSuffix?: string;
    onUpdate?: (all: SubCoderResult[]) => void;
  } = {},
): Promise<SubCoderResult[]> {
  const all: SubCoderResult[] = items.map((it) => ({
    id: it.id,
    label: it.label,
    task: it.task,
    exitCode: -1,
    report: "",
    messages: [],
    stderr: "",
    usage: emptyUsage(),
  }));
  const snapshot = () => opts.onUpdate?.(all.map((r) => ({ ...r })));
  snapshot();

  await mapWithConcurrencyLimit(items, opts.concurrency ?? defaultConcurrency(), async (it, i) => {
    const r = await runSubCoder({
      id: it.id,
      label: it.label,
      task: it.task,
      cwd: it.cwd,
      model: opts.model,
      signal: opts.signal,
      allowedTools: opts.allowedTools,
      timeoutMs: opts.timeoutMs,
      retryOnTimeout: opts.retryOnTimeout,
      reportSuffix: opts.reportSuffix,
      onUpdate: (live) => {
        all[i] = live;
        snapshot();
      },
    });
    all[i] = r;
    snapshot();
    return r;
  });

  return all;
}
