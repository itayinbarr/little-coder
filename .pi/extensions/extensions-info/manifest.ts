// Parsing + rendering for the `/extensions` inventory. Kept separate from
// index.ts so the formatting rules are unit-testable without a pi runtime.

import { basename, dirname } from "node:path";
import { truncateLineToWidth, visibleWidth } from "../_shared/width.ts";

export interface ExtensionManifest {
  /** Shipped with little-coder — always loaded. */
  bundled: string[];
  /** From LITTLE_CODER_EXTRA_EXTENSIONS. */
  env: string[];
  /** From the user extension directory. */
  user: string[];
  /** Where that directory is (or would be), even if it doesn't exist yet. */
  userDir: string | null;
  userDirExists: boolean;
  /** Entries the launcher could not resolve. */
  warnings: string[];
  /** Whether pi's own extension discovery was enabled (--with-pi-extensions). */
  piDiscovery: boolean;
}

const EMPTY: ExtensionManifest = {
  bundled: [],
  env: [],
  user: [],
  userDir: null,
  userDirExists: false,
  warnings: [],
  piDiscovery: false,
};

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === "string") : [];
}

/**
 * Read the launcher's serialized inventory. Returns an empty manifest for any
 * malformed or absent value — `/extensions` reporting "nothing recorded" beats
 * it throwing inside the TUI.
 */
export function parseManifest(raw: string | undefined): ExtensionManifest {
  if (!raw) return { ...EMPTY };
  try {
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return { ...EMPTY };
    return {
      bundled: stringArray(parsed.bundled),
      env: stringArray(parsed.env),
      user: stringArray(parsed.user),
      userDir: typeof parsed.userDir === "string" ? parsed.userDir : null,
      userDirExists: parsed.userDirExists === true,
      warnings: stringArray(parsed.warnings),
      piDiscovery: parsed.piDiscovery === true,
    };
  } catch {
    return { ...EMPTY };
  }
}

/** `.pi/extensions/foo/index.ts` → `foo`; a bare file → its filename. */
export function extensionLabel(path: string): string {
  const base = basename(path);
  if (base === "index.ts" || base === "index.js") return basename(dirname(path));
  return base;
}

/** Replace the home prefix with `~` so paths fit and read cleanly. */
export function tildify(path: string, home: string | undefined): string {
  if (home && home.length > 1 && path.startsWith(home)) return `~${path.slice(home.length)}`;
  return path;
}

const honey = (s: string) => `\x1b[38;2;225;90;31m${s}\x1b[39m`;
const bold = (s: string) => `\x1b[1m${s}\x1b[22m`;
const gray = (s: string) => `\x1b[90m${s}\x1b[39m`;
const yellow = (s: string) => `\x1b[33m${s}\x1b[39m`;

// pi slices a string-array widget to MAX_WIDGET_LINES (10) and appends
// "... (widget truncated)", so anything past that is silently lost — including,
// if we're careless, the load errors that are the most important rows here.
const MAX_PANEL_LINES = 10;

/**
 * Render the inventory as panel lines.
 *
 * Bundled extensions are counted, not listed — there are ~30 and they're all
 * the same install directory, so naming them would bury the part that matters.
 * Yours are listed by path, because "which file is this actually loading" is
 * the whole question when one of them misbehaves.
 *
 * The result is trimmed to fit pi's widget cap, dropping individual paths
 * before it drops a section, so a user with a dozen extensions still sees the
 * counts, the pi-discovery state, and any errors.
 *
 * Every line is capped to `width`: pi-tui throws on overflow (issue #48), so
 * that part is load-bearing rather than cosmetic.
 */
export function panelLines(
  m: ExtensionManifest,
  width: number,
  home: string | undefined = process.env.HOME || process.env.USERPROFILE,
): string[] {
  const header = `${honey("◆")} ${bold("extensions")}  ${gray("(/extensions to close)")}`;
  const detail = (p: string) => `      ${gray(tildify(p, home))}`;

  // Rows that must always survive: the counts, the pi-discovery state, and
  // every load error.
  const fixedCount = 2 + (m.env.length > 0 ? 1 : 0) + 1 + m.warnings.length;
  // …plus the "where to put one" hint, which only appears when there's nothing
  // to list in its place.
  const hintCount = m.user.length === 0 ? 1 : 0;
  let detailBudget = Math.max(0, MAX_PANEL_LINES - 1 - fixedCount - hintCount);

  /** Take up to `budget` paths, summarizing the remainder on one line. */
  const take = (paths: string[]): string[] => {
    if (paths.length <= detailBudget) {
      detailBudget -= paths.length;
      return paths.map(detail);
    }
    // Reserve one line for the "+N more" summary.
    const shown = Math.max(0, detailBudget - 1);
    const out = paths.slice(0, shown).map(detail);
    if (detailBudget > 0) out.push(`      ${gray(`+${paths.length - shown} more`)}`);
    detailBudget = 0;
    return out;
  };

  const lines: string[] = [header];

  lines.push(`  ${honey("bundled")}  ${String(m.bundled.length).padStart(3)} ${gray("loaded")}`);
  lines.push(`  ${honey("yours")}    ${String(m.user.length).padStart(3)} ${gray("loaded")}`);
  lines.push(...take(m.user));
  if (m.user.length === 0) {
    lines.push(
      m.userDir
        ? `      ${gray(`drop a .ts/.js file in ${tildify(m.userDir, home)}`)}`
        : `      ${gray("no config directory could be resolved")}`,
    );
  }

  if (m.env.length > 0) {
    lines.push(
      `  ${honey("env")}      ${String(m.env.length).padStart(3)} ${gray("from LITTLE_CODER_EXTRA_EXTENSIONS")}`,
    );
    lines.push(...take(m.env));
  }

  lines.push(
    m.piDiscovery
      ? `  ${honey("pi extensions")} ${gray("on — pi's own extensions are loading too")}`
      : `  ${honey("pi extensions")} ${gray("off — relaunch with --with-pi-extensions")}`,
  );

  for (const w of m.warnings) {
    lines.push(`  ${yellow("!")} ${yellow(w.replace(/^little-coder:\s*/, ""))}`);
  }

  return lines
    .slice(0, MAX_PANEL_LINES)
    .map((l) => (visibleWidth(l) > width ? truncateLineToWidth(l, width) : l));
}
