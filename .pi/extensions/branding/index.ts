import type { ExtensionAPI, Theme } from "@earendil-works/pi-coding-agent";
import { readFileSync } from "node:fs";
import { basename, dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { truncateLineToWidth } from "../_shared/width.ts";

// Replace pi's built-in startup header + terminal title with little-coder
// branding. The interactive TUI's "pi vX.Y.Z" logo, the "Pi can explain its
// own features..." onboarding line, and the "π - <cwd>" terminal title all
// come from pi's APP_NAME / built-in header; this extension swaps them for
// little-coder's own identity using the public ExtensionUIContext hooks.
//
// Pairs with `.pi/settings.json` setting `"quietStartup": true`, which
// suppresses pi's built-in header AND the loaded-resources dump (the long
// list of extension paths, skills, prompts, themes that used to flood the
// screen on launch). Power users can still run `little-coder --verbose` to
// override quietStartup and see the resource list.
//
// Implementation pattern follows the bundled pi example at
// `node_modules/@earendil-works/pi-coding-agent/examples/extensions/custom-header.ts` —
// the factory returns a duck-typed Component (`render(width): string[]` +
// `invalidate()`), so no deep imports from pi-tui are needed.

const TAGLINE = "A coding agent tuned for small local models";

// Brand accent — "honey" #E15A1F from the brand book (v1.0). Emitted as a
// 24-bit truecolor SGR so the cursor matches the documented hex exactly,
// independent of the active pi theme's named "accent" colour. \x1b[39m resets
// only the foreground, leaving any surrounding bold/style intact.
const HONEY = "\x1b[38;2;225;90;31m";
const honeyFg = (s: string): string => `${HONEY}${s}\x1b[39m`;

function readVersion(): string {
  // .pi/extensions/branding/index.ts → up 3 → package root (where package.json lives).
  // The same path math works in the local checkout (loaded via tsx) and in the
  // installed npm package layout (node_modules/little-coder/.pi/extensions/branding/).
  try {
    const here = dirname(fileURLToPath(import.meta.url));
    const pkgPath = join(here, "..", "..", "..", "package.json");
    const pkg = JSON.parse(readFileSync(pkgPath, "utf-8"));
    if (typeof pkg?.version === "string" && pkg.version.length > 0) return pkg.version;
  } catch {
    // best-effort; fall through
  }
  return "0.0.0";
}

const VERSION = readVersion();

// Exported for tests: the hint row is the first thing every user reads, so a
// key listed here that isn't actually bound is a real defect (issue #74).
export function buildHeader(theme: Theme, width: number): string[] {
  // Brand-book "prompt lockup" (the variant the brand reserves for terminals
  // and dark surfaces): a honey prompt caret, the wordmark in the foreground,
  // and the honey block cursor — "lc▌"'s ready-to-type punchline, applied to
  // the full wordmark. Honey stays the only accent, well under the brand's
  // ~10%-of-layout cap.
  const logo =
    honeyFg("> ") +
    theme.bold("little-coder") +
    honeyFg("▌") +
    theme.fg("dim", ` v${VERSION}`);
  const tagline = theme.fg("muted", TAGLINE);
  const dim = (s: string) => theme.fg("dim", s);
  const sep = theme.fg("muted", " · ");
  // Every key here must be one that actually does something at the prompt.
  // `ctrl-r` used to sit where `ctrl-o` is now: pi binds "expand / more" to
  // `app.tools.expand` (= ctrl+o), and ctrl+r is only bound inside the session
  // tree overlay, so the hint pointed at a key that did nothing (issue #74).
  const hints = [
    `${dim("esc")} interrupt`,
    `${dim("ctrl-l/ctrl-c")} clear/exit`,
    `${dim("/")} commands`,
    `${dim("!")} bash`,
    `${dim("ctrl-o")} more`,
    `${dim("ctrl-q")} plan`,
    `${dim("f2")} research`,
    `${dim("ctrl-h")} keys`,
  ].join(sep);
  // pi-tui throws if any rendered line exceeds the terminal width (issue #48).
  // Truncate every line we hand it so a narrow terminal can't crash the launch.
  return ["", logo, tagline, "", hints, ""].map((l) =>
    l ? truncateLineToWidth(l, width) : l,
  );
}

// Derive a short, human session name from the first user prompt. Returns
// undefined when there's nothing worth naming (empty, or a command/bash line).
// Kept pure + exported so the slug rules are unit-testable.
export function deriveSessionName(text: string): string | undefined {
  const trimmed = text.trim();
  // Slash-commands and `!`-bash aren't tasks — don't name the session after them.
  if (!trimmed || trimmed.startsWith("/") || trimmed.startsWith("!")) return undefined;
  // First line only, first 4 words — cut on word boundaries so it never slices
  // a word mid-way. A "…" is appended only if there were more words.
  const firstLine = trimmed.split(/\r?\n/, 1)[0];
  const allWords = firstLine.split(/\s+/).filter(Boolean);
  if (allWords.length === 0) return undefined;
  const words = allWords.slice(0, 4);
  return allWords.length > words.length ? `${words.join(" ")}…` : words.join(" ");
}

// Title shows the session's name once it has one, else the cwd basename — so a
// `/resume`d or `/name`d session is identifiable in the terminal tab, and
// switching sessions updates the tab (session_start re-asserts on resume).
function setTitle(setter: (t: string) => void, cwd: string, sessionName?: string): void {
  const label = sessionName && sessionName.length > 0 ? sessionName : basename(cwd);
  setter(`little-coder · ${label}`);
}

export default function (pi: ExtensionAPI) {
  // session_start fires on initial load AND on every session switch.
  // Pi's updateTerminalTitle() runs in init() *after* session_start, so our
  // setTitle here gets clobbered back to "π - <cwd>". We reassert the title
  // on turn_start and turn_end too — pi calls updateTerminalTitle at the same
  // points (interactive-mode.js:1179, 1346, 3971), so re-setting on every
  // turn keeps our "little-coder - <cwd>" winning for the duration of a
  // session.
  const reassertTitle = (ctx: { hasUI: boolean; cwd: string; ui: { setTitle: (t: string) => void } }) => {
    if (!ctx.hasUI) return;
    setTitle(ctx.ui.setTitle.bind(ctx.ui), ctx.cwd, safeGetSessionName(pi));
  };

  pi.on("session_start", async (_event, ctx) => {
    if (!ctx.hasUI) return;

    ctx.ui.setHeader((_tui, theme) => ({
      render(width: number): string[] {
        return buildHeader(theme, width);
      },
      invalidate() {},
    }));

    reassertTitle(ctx);
  });

  // Auto-name an as-yet-unnamed session after the user's first real prompt, so
  // it's identifiable in `/resume` and the tab title without anyone running
  // `/name`. Only genuine interactive typing names a session — never the
  // benchmark RPC path or programmatic follow-ups (thinking-budget nudges,
  // plan-mode synthesis). `/name` still overrides at any time.
  pi.on("input", async (event, ctx) => {
    if ((event as any).source !== "interactive") return;
    if (safeGetSessionName(pi)) return; // already named (auto or via /name)
    const name = deriveSessionName(String((event as any).text ?? ""));
    if (!name) return;
    try {
      pi.setSessionName(name);
    } catch {
      // older SDK without setSessionName — title still falls back to cwd
    }
    reassertTitle(ctx);
  });

  // Pi calls updateTerminalTitle() at turn boundaries (interactive-mode.js),
  // which would clobber ours back to "π - <cwd>"; re-assert at the same points.
  pi.on("turn_start", async (_event, ctx) => reassertTitle(ctx));
  pi.on("turn_end", async (_event, ctx) => reassertTitle(ctx));
}

function safeGetSessionName(pi: ExtensionAPI): string | undefined {
  try {
    return typeof pi.getSessionName === "function" ? pi.getSessionName() : undefined;
  } catch {
    return undefined;
  }
}
