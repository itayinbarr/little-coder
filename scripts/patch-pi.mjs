#!/usr/bin/env node
// Idempotent, dependency-free, best-effort patches to the bundled pi runtime
// for things little-coder can't express through pi's extension API.
//
// little-coder treats pi as a substrate it owns, not a boundary — but pi is a
// normal npm dependency, so we can't ship a modified copy of it. Instead the
// launcher applies small source edits to the installed pi on every launch by
// calling applyPiPatches().
//
// Launch-time is the only hook there is, by design. little-coder ships NO npm
// install scripts: a `postinstall` was the one thing tripping Socket's AI
// malware scan (issue #75), and it was already redundant — the in-app
// `/update` and the launcher's self-update both install with --ignore-scripts
// (issue #50), so a postinstall never ran for anyone upgrading. Patching from
// the launcher also means we patch wherever pi actually lives, including
// bun's flat global layout, and it self-heals if pi is reinstalled under us.
//
// Contract: NEVER throw. A failed patch must not break a launch — the only
// consequence is the un-patched UI.
//
// Current patches:
//   1. Suppress pi's bare "Operation aborted" assistant-message marker. Harness
//      interventions surface their own single "harness intervention: …" line,
//      and a user ESC is self-evident; the stacked red marker was noise. A
//      genuine custom errorMessage (not the default abort string) is preserved.

import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const PI_PKG = "@earendil-works/pi-coding-agent";

const ABORT_MARKER_PATCH = {
  rel: "dist/modes/interactive/components/assistant-message.js",
  // Skip if our edit is already present (idempotency).
  applied: 'little-coder patch: suppress the bare "Operation aborted" marker',
  // Exact original block shipped by pi 0.75.x. If it doesn't match (pi changed),
  // we skip silently rather than guess.
  find:
    '                const abortMessage = message.errorMessage && message.errorMessage !== "Request was aborted"\n' +
    "                    ? message.errorMessage\n" +
    '                    : "Operation aborted";\n' +
    "                if (hasVisibleContent) {\n" +
    "                    this.contentContainer.addChild(new Spacer(1));\n" +
    "                }\n" +
    "                else {\n" +
    "                    this.contentContainer.addChild(new Spacer(1));\n" +
    "                }\n" +
    "                this.contentContainer.addChild(new Text(theme.fg(\"error\", abortMessage), 1, 0));",
  replace:
    '                // little-coder patch: suppress the bare "Operation aborted" marker.\n' +
    "                // Harness interventions surface their own single\n" +
    '                // "harness intervention: …" line, and a user ESC is self-evident.\n' +
    "                // A genuine custom errorMessage is still shown.\n" +
    '                const abortMessage = message.errorMessage && message.errorMessage !== "Request was aborted"\n' +
    "                    ? message.errorMessage\n" +
    "                    : null;\n" +
    "                if (abortMessage) {\n" +
    "                    this.contentContainer.addChild(new Spacer(1));\n" +
    "                    this.contentContainer.addChild(new Text(theme.fg(\"error\", abortMessage), 1, 0));\n" +
    "                }",
};

export const PATCHES = [ABORT_MARKER_PATCH];

export function resolvePiRoot(piRootOverride) {
  if (piRootOverride && existsSync(join(piRootOverride, "package.json"))) {
    return piRootOverride;
  }
  // 1) Module resolution (respects npm hoisting).
  try {
    const require = createRequire(import.meta.url);
    return dirname(require.resolve(`${PI_PKG}/package.json`));
  } catch {
    // pi may not export package.json — fall through.
  }
  // 2) Nested node_modules next to this package root (scripts/ -> ..).
  try {
    const here = dirname(fileURLToPath(import.meta.url));
    const nested = join(here, "..", "node_modules", ...PI_PKG.split("/"));
    if (existsSync(join(nested, "package.json"))) return nested;
  } catch {
    // ignore
  }
  return null;
}

/**
 * Apply all pi patches in place. Best-effort and idempotent.
 * @param {string} [piRootOverride] Known pi package root. The launcher passes
 *   its already-resolved path (the layout it actually spawns); when omitted we
 *   fall back to resolving pi ourselves.
 */
export function applyPiPatches(piRootOverride) {
  const piRoot = resolvePiRoot(piRootOverride);
  if (!piRoot) return;
  for (const p of PATCHES) {
    try {
      const file = join(piRoot, p.rel);
      if (!existsSync(file)) continue;
      const src = readFileSync(file, "utf8");
      if (src.includes(p.applied)) continue; // already patched
      if (!src.includes(p.find)) continue; // pi changed — skip silently
      writeFileSync(file, src.replace(p.find, p.replace));
    } catch {
      // best-effort: never break install or launch
    }
  }
}
