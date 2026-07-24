import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { terminalColumns, truncateLineToWidth, visibleWidth } from "../_shared/width.ts";

// Shortcuts-help overlay — a ctrl+h toggle that shows a compact, always-current
// list of the keys worth knowing right below the input (issue #55). New hotkeys
// keep getting added (plan-mode's ctrl+q, the thinking-level cycle, …) and they
// aren't discoverable to newer users; this panel surfaces them on demand.
//
// Why ctrl+h: it's genuinely unbound — neither pi nor the emacs-style editor
// claims it, and it isn't in pi's `restrictOverride` reserved set — so the
// shortcut registers cleanly with no startup "[Extension issues]" conflict and
// without shadowing an editor key. Mnemonic: "help".
//
// This panel is the *discoverable* view; pi's built-in `/hotkeys` command is the
// authoritative full reference. Because both little-coder shortcuts (ctrl+q and
// this ctrl+h) are registered via pi.registerShortcut() with a description, they
// also appear automatically in `/hotkeys`'s "Extensions" table.

const honey = (s: string) => `\x1b[38;2;225;90;31m${s}\x1b[39m`;
const bold = (s: string) => `\x1b[1m${s}\x1b[22m`;
const gray = (s: string) => `\x1b[90m${s}\x1b[39m`;
const WIDGET_KEY = "shortcuts-help";

// [keys, description]. Keep this to the keys a user actually reaches for; the
// bindings are those of the bundled pi (0.79.x) + little-coder's own. `/hotkeys`
// holds the exhaustive list, so this stays a curated subset.
// Every row must name a key that is actually bound — a panel that lists a
// dead key is worse than no panel (issue #74, where the startup header
// advertised ctrl-r for "more" but pi binds that to ctrl-o).
const ROWS: ReadonlyArray<readonly [string, string]> = [
  ["ctrl-q", "toggle plan mode"],
  ["f2", "toggle deep research"],
  ["ctrl-h", "toggle this shortcuts panel"],
  ["shift-tab", "cycle thinking level"],
  ["ctrl-p", "cycle model"],
  ["ctrl-t", "toggle thinking blocks"],
  ["ctrl-o", "toggle tool output"],
  ["esc", "interrupt"],
  ["/", "commands"],
  ["!", "bash"],
  ["/hotkeys", "full keybinding reference"],
];

// pi renders a string-array widget through `content.slice(0, MAX_WIDGET_LINES)`
// and appends "... (widget truncated)" past that (interactive-mode.js). The cap
// is 10, and a one-per-line panel of this list overflows it — which silently ate
// the `/hotkeys` row, i.e. the pointer to the authoritative reference. So the
// panel lays out in two columns and fits.
const MAX_PANEL_LINES = 10;
const GUTTER = "   ";

/** Render `rows` as one aligned column: `  key   description`. */
function column(rows: ReadonlyArray<readonly [string, string]>): string[] {
  const keyWidth = rows.reduce((m, [k]) => Math.max(m, visibleWidth(k)), 0);
  return rows.map(([k, desc]) => {
    const pad = " ".repeat(keyWidth - visibleWidth(k));
    return `  ${honey(k)}${pad}  ${gray(desc)}`;
  });
}

/** Visible width of the widest line in `lines`. */
function widest(lines: string[]): number {
  return lines.reduce((m, l) => Math.max(m, visibleWidth(l)), 0);
}

// Build the panel lines. Keys are padded to a common width so descriptions align
// into clean columns. Every line is capped to the terminal width — pi-tui throws
// on overflow (issue #48), so that part is load-bearing, not cosmetic.
export function panelLines(width: number = terminalColumns()): string[] {
  const header = `${honey("◆")} ${bold("shortcuts")}  ${gray("(ctrl-h to close)")}`;
  const bodyBudget = MAX_PANEL_LINES - 1; // header takes one

  // Two columns, split down the middle so reading order stays top-to-bottom
  // within each column.
  const half = Math.ceil(ROWS.length / 2);
  const left = column(ROWS.slice(0, half));
  const right = column(ROWS.slice(half));
  const leftWidth = widest(left);

  const twoColumn = left.map((l, i) => {
    const r = right[i];
    if (!r) return l;
    return l + " ".repeat(leftWidth - visibleWidth(l)) + GUTTER + r.replace(/^ {2}/, "");
  });

  // Only use two columns if they genuinely fit — on a narrow terminal a
  // truncated second column is worse than a shorter list.
  const fits = widest(twoColumn) <= width;
  const body = fits ? twoColumn : column(ROWS).slice(0, bodyBudget);

  return [header, ...body.slice(0, bodyBudget)].map((l) => truncateLineToWidth(l, width));
}

let helpOn = false;

function setPanel(ctx: any, on: boolean): void {
  if (!ctx?.hasUI) return;
  ctx.ui.setWidget(WIDGET_KEY, on ? panelLines() : undefined, { placement: "belowEditor" });
}

export default function (pi: ExtensionAPI) {
  pi.registerShortcut("ctrl+h", {
    description: "Toggle keyboard-shortcuts panel",
    handler: (ctx: any) => {
      helpOn = !helpOn;
      setPanel(ctx, helpOn);
    },
  });

  // Default to hidden on every (re)load so a resumed session doesn't surface a
  // stale panel.
  pi.on("session_start", async (_event, ctx) => {
    helpOn = false;
    setPanel(ctx, false);
  });
}
