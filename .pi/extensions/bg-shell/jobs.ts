// Pure logic for background shell jobs: wake rules, output buffering, and the
// bounded payload the model actually sees. No child processes and no pi
// runtime here, so every decision below is unit-testable.
//
// The problem this exists to solve: pi's `bash` is fire-and-wait, so a long job
// either blocks the turn for its whole duration or gets backgrounded and then
// POLLED — burning a turn, a slice of a small context window, and thirty
// seconds of local inference to learn that training is still on epoch 3. If a
// fine-tune runs six hours, checking every five minutes is 71 wasted turns.
//
// So the clock is not the trigger. When the model starts a job it declares what
// is worth being woken for, and the harness stays silent until one of those
// things happens. Six hours of progress bars cost nothing; a traceback at
// minute 40 costs one turn, immediately.

export type WakeKind = "exit" | "match" | "silence" | "milestone";

/** How urgently a wake event reaches the agent. Maps onto pi's sendMessage
 *  delivery modes — see laneDelivery(). */
export type Lane = "now" | "soon" | "idle";

export interface WakeRules {
  /** Wake when the process exits. Defaults true: an exited job the model still
   *  believes is running is the worst state to be in. */
  exit: boolean;
  /** Patterns worth waking for. Treated as regex, falling back to a literal
   *  substring when the string is not a valid regex (models write plain text
   *  like "CUDA out of memory" far more often than they write anchors). */
  match: string[];
  /** Wake if the job produced output and then went quiet for this long. */
  silenceMs?: number;
  /** Throttle a chatty pattern: only wake on every Nth match. */
  everyNMatches?: number;
}

export const DEFAULT_RULES: WakeRules = { exit: true, match: [] };

/** Lines kept per job. The buffer is the model's ability to look back, so it
 *  has to be generous — but it lives in the harness, never in the context
 *  window, so generous is cheap. */
export const MAX_BUFFER_LINES = 5000;
/** Lines of context included around a matching line in a wake payload. */
export const WAKE_CONTEXT_LINES = 12;
/** Never wake for the same job more often than this, whatever the rules say.
 *  A job that matches its own error pattern every second must not be able to
 *  drive the agent in a loop. */
export const MIN_WAKE_INTERVAL_MS = 15_000;

// ── Duration parsing ────────────────────────────────────────────────────

/** Parse "45s" / "10m" / "2h" / a bare number of seconds. Null when unparseable
 *  so a typo disables the rule loudly rather than silently meaning 0ms. */
export function parseDuration(v: unknown): number | null {
  if (typeof v === "number" && Number.isFinite(v) && v > 0) return Math.round(v * 1000);
  if (typeof v !== "string") return null;
  const m = v.trim().match(/^(\d+(?:\.\d+)?)\s*(ms|s|m|h)?$/i);
  if (!m) return null;
  const n = parseFloat(m[1]);
  if (!Number.isFinite(n) || n <= 0) return null;
  switch ((m[2] || "s").toLowerCase()) {
    case "ms": return Math.round(n);
    case "s": return Math.round(n * 1000);
    case "m": return Math.round(n * 60_000);
    case "h": return Math.round(n * 3_600_000);
    default: return null;
  }
}

/** Build WakeRules from whatever the model passed as `wake_on`. Permissive by
 *  design: a malformed field falls back to its default rather than failing the
 *  whole call, because a job that failed to start is strictly worse than a job
 *  with one rule missing. */
export function normalizeRules(raw: any): WakeRules {
  const out: WakeRules = { exit: true, match: [] };
  if (!raw || typeof raw !== "object") return out;
  if (raw.exit === false) out.exit = false;

  const m = raw.match;
  if (typeof m === "string") out.match = [m];
  else if (Array.isArray(m)) out.match = m.filter((x: any) => typeof x === "string" && x.length > 0);

  const sil = parseDuration(raw.silence);
  if (sil) out.silenceMs = sil;

  const n = raw.every_n_matches ?? raw.everyNMatches;
  if (typeof n === "number" && Number.isFinite(n) && n > 1) out.everyNMatches = Math.floor(n);

  return out;
}

/** Compile a pattern to a matcher. Invalid regex degrades to a literal
 *  substring test rather than throwing — the model writes prose, not /re/. */
export function compileMatcher(pattern: string): (line: string) => boolean {
  try {
    const re = new RegExp(pattern, "i");
    return (line) => re.test(line);
  } catch {
    const needle = pattern.toLowerCase();
    return (line) => line.toLowerCase().includes(needle);
  }
}

// ── Ring buffer ─────────────────────────────────────────────────────────

/** Line buffer with a hard cap. Keeps a running count of everything ever
 *  written so ShellLog offsets stay stable after old lines are dropped. */
export class LineBuffer {
  private lines: string[] = [];
  private dropped = 0;

  constructor(private max = MAX_BUFFER_LINES) {}

  push(line: string): void {
    this.lines.push(line);
    if (this.lines.length > this.max) {
      this.dropped += this.lines.length - this.max;
      this.lines = this.lines.slice(-this.max);
    }
  }

  /** Total lines ever written, including dropped ones. */
  get total(): number {
    return this.dropped + this.lines.length;
  }

  get droppedCount(): number {
    return this.dropped;
  }

  /** The last `n` lines. */
  tail(n: number): string[] {
    return this.lines.slice(-Math.max(0, n));
  }

  /** Lines from absolute index `from` (in `total` coordinates), up to `limit`.
   *  Clamps into whatever is still retained. */
  slice(from: number, limit: number): { lines: string[]; from: number; nextOffset: number } {
    const start = Math.max(from, this.dropped);
    const localStart = start - this.dropped;
    const lines = this.lines.slice(localStart, localStart + Math.max(0, limit));
    return { lines, from: start, nextOffset: start + lines.length };
  }

  /** The last `context` lines ending at the most recent line. */
  around(context: number): string[] {
    return this.tail(context);
  }
}

// ── Wake decisions ──────────────────────────────────────────────────────

export interface JobWakeState {
  /** Matches seen so far, for every_n_matches throttling. */
  matchCount: number;
  /** When we last woke the agent for this job. */
  lastWakeAt: number;
  /** Whether a stall wake has already fired for the current quiet period. */
  stallNotified: boolean;
}

export interface WakeEvent {
  kind: WakeKind;
  lane: Lane;
  /** Short human reason, e.g. `matched "Traceback"`. */
  reason: string;
}

/** Patterns that mean "this is broken", which get the urgent lane even when the
 *  model listed them as ordinary matches. Anything the model explicitly asked
 *  about is relevant; these are the subset that invalidate what it believes. */
const ERROR_ISH = /traceback|out of memory|oom|fatal|panic|segmentation fault|\berror\b|exception/i;

/** The first configured pattern this line matches, or null. Exported so the
 *  caller can decide-once: whether a line matched drives BOTH the match counter
 *  and the wake decision, and computing it twice with two different notions of
 *  "matches" is how every_n_matches quietly stops lining up with reality. */
export function findMatch(line: string, rules: WakeRules): string | null {
  for (const p of rules.match) {
    if (compileMatcher(p)(line)) return p;
  }
  return null;
}

/**
 * Decide whether a matched line should wake the agent.
 *
 * `matchCount` is the count INCLUDING this match — the caller increments first,
 * so throttling counts every occurrence even when the wake is suppressed.
 * Otherwise a throttled pattern could never reach N and would wake either
 * always or never.
 */
export function evaluateMatch(
  hit: string,
  line: string,
  rules: WakeRules,
  state: JobWakeState,
  matchCount: number,
  now: number,
): WakeEvent | null {
  if (rules.everyNMatches && matchCount % rules.everyNMatches !== 0) return null;
  // The loop guard: a job that matches its own error pattern every second must
  // not be able to drive the agent in circles.
  if (now - state.lastWakeAt < MIN_WAKE_INTERVAL_MS) return null;

  const errorish = ERROR_ISH.test(line);
  return {
    kind: rules.everyNMatches ? "milestone" : "match",
    lane: errorish ? "now" : "soon",
    reason: `matched ${JSON.stringify(hit)}`,
  };
}

/** Decide the lane for a process exit. A non-zero exit is urgent because every
 *  subsequent step the model takes rests on a false premise until it knows. */
export function evaluateExit(exitCode: number | null, rules: WakeRules): WakeEvent | null {
  if (!rules.exit) return null;
  const failed = exitCode !== 0;
  return {
    kind: "exit",
    lane: failed ? "now" : "soon",
    reason: failed ? `exited ${exitCode}` : "exited 0",
  };
}

/** Decide whether a quiet job counts as stalled. Only fires once per quiet
 *  period, and only for a job that produced output first — a job that is
 *  legitimately silent from the start (a compile) is not stalled. */
export function evaluateSilence(
  rules: WakeRules,
  state: JobWakeState,
  lastOutputAt: number | null,
  now: number,
): WakeEvent | null {
  if (!rules.silenceMs || state.stallNotified || lastOutputAt === null) return null;
  if (now - lastOutputAt < rules.silenceMs) return null;
  return {
    kind: "silence",
    lane: "soon",
    reason: `no output for ${Math.round((now - lastOutputAt) / 1000)}s`,
  };
}

/** pi sendMessage delivery options for a lane.
 *
 *  "steer"    — after the current tool calls, before the next LLM call.
 *  "followUp" — once the agent has no more tool calls.
 *  "nextTurn" — queued; interrupts nothing and triggers nothing. */
export function laneDelivery(lane: Lane): { deliverAs: string; triggerTurn?: boolean } {
  switch (lane) {
    case "now": return { deliverAs: "steer", triggerTurn: true };
    case "soon": return { deliverAs: "followUp", triggerTurn: true };
    case "idle": return { deliverAs: "nextTurn" };
  }
}

// ── Payload ─────────────────────────────────────────────────────────────

/**
 * Wrap a command so the job kills itself when little-coder goes away.
 *
 * Signal handlers cover a clean exit and ctrl+c, but they cannot cover SIGKILL,
 * a crash, or a terminal that vanishes — and an orphaned training run holds GPU
 * memory on a box whose entire constraint is 8GB of it. So the guarantee is
 * pushed into the job: a watchdog polls for the parent pid and takes the whole
 * process group down with it when the parent disappears.
 *
 * This requires the job to be its OWN process group (spawn detached), which is
 * why `kill -TERM 0` is safe here — it signals the job's group, never
 * little-coder's. The watchdog is killed on the normal path so a finished job
 * leaves nothing behind, and the command's exit status is preserved.
 */
export function wrapWithParentWatchdog(command: string, parentPid: number, pollSeconds = 5): string {
  return [
    `__lc_parent=${parentPid}`,
    // The watchdog's stdio is redirected away from the job's pipes. Otherwise
    // its `sleep` inherits them, and since killing the subshell does not kill
    // that sleep, the pipes stay open after the command finishes — Node's
    // `close` fires only once stdio is done, so the exit wake would arrive
    // seconds late or, if the sleep outlives us, not at all.
    `( while kill -0 "$__lc_parent" 2>/dev/null; do sleep ${pollSeconds}; done; kill -TERM 0 2>/dev/null ) >/dev/null 2>&1 </dev/null &`,
    `__lc_watchdog=$!`,
    // The braces must be newline-separated, not `{ cmd ; }` on one line: the
    // command is arbitrary user text and may legitimately end in a comment, a
    // heredoc, or a trailing backslash, any of which would swallow a `;`.
    `{`,
    command,
    `}`,
    `__lc_rc=$?`,
    `kill "$__lc_watchdog" 2>/dev/null`,
    `exit $__lc_rc`,
  ].join("\n");
}

export function formatElapsed(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m${String(s % 60).padStart(2, "0")}s`;
  return `${Math.floor(m / 60)}h${String(m % 60).padStart(2, "0")}m`;
}

export interface WakePayloadInput {
  id: string;
  label: string;
  command: string;
  event: WakeEvent;
  elapsedMs: number;
  exitCode?: number | null;
  lines: string[];
  totalLines: number;
}

/**
 * The bounded message the model receives. Deliberately NOT the whole log: a
 * progress bar can be a hundred thousand lines, and dumping it would destroy
 * the context window this project exists to conserve. Same principle as the
 * sub-coder report — the child's full transcript stays out, only a digest goes
 * in — and the model can always pull more with ShellLog if the digest warrants.
 */
export function formatWakePayload(p: WakePayloadInput): string {
  const head = [
    `background job "${p.label}" (${p.id}) — ${p.event.reason}`,
    `command: ${p.command}`,
    `running: ${formatElapsed(p.elapsedMs)}${
      p.exitCode !== undefined && p.exitCode !== null ? ` · exit ${p.exitCode}` : ""
    }`,
  ];
  const body = p.lines.length > 0
    ? [`last ${p.lines.length} of ${p.totalLines} lines:`, "```", ...p.lines, "```"]
    : ["(no output)"];
  const tail =
    p.event.kind === "exit"
      ? []
      : [`ShellLog({"id":"${p.id}"}) for more. The job is still running.`];
  return [...head, "", ...body, ...tail].join("\n");
}
