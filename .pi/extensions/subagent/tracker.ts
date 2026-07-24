// Live sub-coder tracker — a small animated panel above the input showing each
// running/finished sub-coder, its status, elapsed time and current activity.
//
// Driven by string[] content re-set on a timer (the spinner + clock need to
// tick, which event updates alone can't do). Colors are raw 24-bit/SGR escapes
// (same approach as branding's honey accent) so the panel doesn't depend on the
// active theme and the string[] form of setWidget can be used directly.

import { summarizeActivity, type SubCoderResult } from "./spawn.ts";
import { terminalColumns, truncateLineToWidth } from "../_shared/width.ts";

const SPINNER = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];

// pi renders a string-array widget through `content.slice(0, MAX_WIDGET_LINES)`
// (interactive-mode.js; the cap is 10) and appends a "... (widget truncated)"
// line past that. One line goes to our header and one may go to the
// "+N earlier" summary, leaving 8 rows of sub-coders.
const MAX_ROWS = 8;

// Brand honey (matches branding/index.ts) + plain SGR status colors.
const honey = (s: string) => `\x1b[38;2;225;90;31m${s}\x1b[39m`;
const green = (s: string) => `\x1b[32m${s}\x1b[39m`;
const red = (s: string) => `\x1b[31m${s}\x1b[39m`;
const gray = (s: string) => `\x1b[90m${s}\x1b[39m`;

function fmtElapsed(ms: number): string {
  const total = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${m}:${s.toString().padStart(2, "0")}`;
}

function padEnd(s: string, n: number): string {
  return s.length >= n ? s : s + " ".repeat(n - s.length);
}

export interface TrackerUI {
  hasUI: boolean;
  ui: {
    setWidget: (
      key: string,
      content: string[] | undefined,
      options?: { placement?: "aboveEditor" | "belowEditor" },
    ) => void;
  };
}

export class SubCoderTracker {
  private readonly key: string;
  private readonly placement: "aboveEditor" | "belowEditor";
  private results = new Map<string, SubCoderResult>();
  private order: string[] = [];
  private startedAt = new Map<string, number>();
  private finishedAt = new Map<string, number>();
  private timer: ReturnType<typeof setInterval> | null = null;
  private lastFrame = "";

  constructor(
    private ctx: TrackerUI,
    opts: { key?: string; placement?: "aboveEditor" | "belowEditor"; totalSince?: number } = {},
  ) {
    this.key = opts.key ?? "subcoders";
    this.placement = opts.placement ?? "aboveEditor";
    this.totalSince = opts.totalSince;
  }

  // When set, the header shows a running total-elapsed timer (the overall
  // process time, not just per-sub-coder).
  private totalSince?: number;

  /** Register the items and start the animation timer. */
  begin(items: { id: string; label: string }[]): void {
    if (!this.ctx.hasUI || items.length === 0) return;
    const now = Date.now();
    for (const it of items) {
      if (!this.startedAt.has(it.id)) {
        this.order.push(it.id);
        this.startedAt.set(it.id, now);
        this.results.set(it.id, {
          id: it.id,
          label: it.label,
          task: "",
          exitCode: -1,
          report: "",
          messages: [],
          stderr: "",
          usage: { input: 0, output: 0, cost: 0, turns: 0, contextTokens: 0 },
        });
      }
    }
    this.render();
    if (!this.timer) this.timer = setInterval(() => this.render(), 120);
  }

  /** Feed a fresh snapshot of all results (from runSubCodersConcurrent). */
  update(results: SubCoderResult[]): void {
    if (!this.ctx.hasUI) return;
    const now = Date.now();
    for (const r of results) {
      if (!this.startedAt.has(r.id)) {
        this.order.push(r.id);
        this.startedAt.set(r.id, now);
      }
      this.results.set(r.id, r);
      if (r.exitCode !== -1 && !this.finishedAt.has(r.id)) this.finishedAt.set(r.id, now);
    }
  }

  /** Stop the timer, paint a final static frame, then clear the panel. */
  end(): void {
    if (this.timer) {
      clearInterval(this.timer);
      this.timer = null;
    }
    if (!this.ctx.hasUI) return;
    this.render();
    this.ctx.ui.setWidget(this.key, undefined, { placement: this.placement });
  }

  private render(): void {
    if (!this.ctx.hasUI || this.order.length === 0) return;
    const now = Date.now();
    const frame = SPINNER[Math.floor(now / 100) % SPINNER.length];

    const items = this.order.map((id) => this.results.get(id)!).filter(Boolean);
    const done = items.filter((r) => r.exitCode !== -1).length;
    const labelWidth = Math.min(18, Math.max(...items.map((r) => r.label.length), 4));

    const total = this.totalSince !== undefined ? ` · ${fmtElapsed(now - this.totalSince)}` : "";
    const header = `${honey("sub-coders")} ${gray(`· ${done}/${items.length} done${total}`)}`;

    // `begin()` appends and never resets, so a session with several dispatch
    // turns accumulates rows indefinitely. pi slices a widget to
    // MAX_WIDGET_LINES (10) and appends "... (widget truncated)", which would
    // drop rows from the END — i.e. hide the sub-coders that are actually
    // RUNNING behind a backlog of finished ones, which is exactly backwards.
    // Show every running sub-coder, fill the rest with the most recently
    // finished, and account for the remainder on one line.
    const running = items.filter((r) => r.exitCode === -1);
    const finished = items.filter((r) => r.exitCode !== -1);
    // Indices rather than negative slice offsets on purpose: `slice(-0)` is
    // `slice(0)`, i.e. the WHOLE array, so a naive `slice(-remainingSlots)`
    // silently shows everything at exactly the moment there's no room left.
    const runningShown =
      running.length > MAX_ROWS ? running.slice(running.length - MAX_ROWS) : running;
    const finishedSlots = MAX_ROWS - runningShown.length;
    const finishedShown =
      finishedSlots > 0 ? finished.slice(Math.max(0, finished.length - finishedSlots)) : [];
    const shown = [...runningShown, ...finishedShown];
    const hidden = items.length - shown.length;

    const rows = shown.map((r) => {
      const isRunning = r.exitCode === -1;
      const icon = isRunning ? honey(frame) : r.exitCode === 0 ? green("✓") : red("✗");
      const end = this.finishedAt.get(r.id) ?? now;
      const elapsed = fmtElapsed(end - (this.startedAt.get(r.id) ?? now));
      const activity = summarizeActivity(r);
      return `  ${icon} ${padEnd(r.label, labelWidth)}  ${gray(padEnd(elapsed, 5))}  ${gray(activity)}`;
    });
    if (hidden > 0) rows.push(`  ${gray(`… +${hidden} earlier sub-coders`)}`);

    // Cap every line to the active terminal width — pi-tui throws if a custom
    // widget renders a line wider than the terminal (issue #48). The activity
    // text in rows can be unbounded (failed sub-coders surface raw stderr /
    // errorMessage, which routinely runs ~200 chars), so without this each
    // failing dispatch turn would crash the whole session.
    const width = terminalColumns();
    const lines = [header, ...rows].map((l) => truncateLineToWidth(l, width));
    const frameKey = lines.join("\n");
    if (frameKey === this.lastFrame) return; // diff-guard: skip identical repaints
    this.lastFrame = frameKey;
    this.ctx.ui.setWidget(this.key, lines, { placement: this.placement });
  }
}
