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
//   2. Repair raw control characters inside a JSON-string `edits` argument to
//      the edit tool, so a multi-line replacement from a small local model is
//      recoverable instead of deadlocking the run (issue #127).

import { readFileSync, writeFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const PI_PKG = "@earendil-works/pi-coding-agent";

const ABORT_MARKER_PATCH = {
  rel: "dist/modes/interactive/components/assistant-message.js",
  // Skip if our edit is already present (idempotency).
  applied: 'little-coder patch: suppress the bare "Operation aborted" marker',
  // Exact original block shipped by pi 0.83.x. If it doesn't match (pi changed),
  // we skip silently rather than guess.
  find:
    '                const abortMessage = message.errorMessage && message.errorMessage !== "Request was aborted"\n' +
    "                    ? message.errorMessage\n" +
    '                    : "Operation aborted";\n' +
    "                this.contentContainer.addChild(new Spacer(1));\n" +
    "                this.contentContainer.addChild(new Text(theme.fg(\"error\", abortMessage), this.outputPad, 0));",
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
    "                    this.contentContainer.addChild(new Text(theme.fg(\"error\", abortMessage), this.outputPad, 0));\n" +
    "                }",
};

// ── patch 2: edit-tool `edits` JSON repair (issue #127) ─────────────────────
//
// pi already handles a model that sends `edits` as a JSON *string* instead of
// an array. That recovery is a bare `JSON.parse` in a `try`, and it fails on
// the single most common way a small local model writes one: raw, unescaped
// newlines inside the `oldText` / `newText` values, which is what multi-line
// code IS. `JSON.parse` throws "Bad control character in string literal", the
// empty `catch` swallows it, `edits` stays a string, and schema validation
// then refuses the call with `edits.0: must be object`.
//
// The consequence is worse than one failed call. `write` is refused for a file
// that already exists (write-guard, by design), and `edit` cannot be produced,
// so a model that has correctly diagnosed a bug has no way left to deliver the
// patch. brlucasdx measured six of these in a single session.
//
// This cannot be fixed from an extension: pi's agent loop runs
// prepareArguments -> validateToolArguments -> beforeToolCall, so validation
// has already rejected the call before any `tool_call` hook sees it. Patching
// pi's own recovery is the only place the repair can live.

/**
 * Escape raw CR / LF / TAB that appear INSIDE JSON string literals, leaving
 * structural whitespace between tokens untouched.
 *
 * Quote/escape state is tracked so a `"` that is itself escaped (`\"`) does not
 * flip the parser out of the string, which is exactly the case in code being
 * edited. Total and allocation-cheap; a string that needs no repair comes back
 * unchanged and re-parses identically.
 *
 * NOTE: this function is injected into pi's source verbatim via
 * `String(repairJsonControlChars)`, so it must not reference anything outside
 * its own body. The export exists so the unit tests exercise the SAME code that
 * ships, rather than a copy that can drift from it.
 */
export function repairJsonControlChars(text) {
  let out = "";
  let inStr = false;
  let esc = false;
  for (const ch of text) {
    if (esc) {
      out += ch;
      esc = false;
      continue;
    }
    if (ch === "\\") {
      out += ch;
      esc = true;
      continue;
    }
    if (ch === '"') {
      inStr = !inStr;
      out += ch;
      continue;
    }
    if (inStr) {
      if (ch === "\n") {
        out += "\\n";
        continue;
      }
      if (ch === "\r") {
        out += "\\r";
        continue;
      }
      if (ch === "\t") {
        out += "\\t";
        continue;
      }
    }
    out += ch;
  }
  return out;
}

const EDIT_REPAIR_APPLIED = "little-coder patch: repair raw control chars in a JSON-string `edits`";

/** The replacement `catch` body, with the repair function inlined. */
function editRepairCatch(indent) {
  const i = " ".repeat(indent);
  return (
    `catch {\n` +
    `${i}    // ${EDIT_REPAIR_APPLIED} (issue #127).\n` +
    `${i}    // Small local models emit literal newlines inside oldText/newText;\n` +
    `${i}    // JSON.parse rejects those as "Bad control character in string\n` +
    `${i}    // literal", and the original empty catch left \`edits\` a string for\n` +
    `${i}    // schema validation to refuse. With write refused for an existing\n` +
    `${i}    // file, that left the model no way to deliver a patch at all.\n` +
    `${i}    try {\n` +
    `${i}        const repair = ${String(repairJsonControlChars).split("\n").join(`\n${i}        `)};\n` +
    `${i}        const repaired = JSON.parse(repair(args.edits));\n` +
    `${i}        if (Array.isArray(repaired))\n` +
    `${i}            args.edits = repaired;\n` +
    `${i}    }\n` +
    `${i}    catch { }\n` +
    `${i}}`
  );
}

// pi ships two copies of the edit tool: the coding agent's own (used by the
// TUI and by `-p`) and pi-agent-core's harness copy (the path brlucasdx
// quoted). They differ only in formatting, so each gets its own exact `find`.
const EDIT_REPAIR_PATCHES = [
  {
    rel: "dist/core/tools/edit.js",
    applied: EDIT_REPAIR_APPLIED,
    find:
      "            if (Array.isArray(parsed))\n" +
      "                args.edits = parsed;\n" +
      "        }\n" +
      "        catch { }\n" +
      "    }\n" +
      "    const legacy = args;",
    replace:
      "            if (Array.isArray(parsed))\n" +
      "                args.edits = parsed;\n" +
      "        }\n" +
      "        " + editRepairCatch(8) + "\n" +
      "    }\n" +
      "    const legacy = args;",
  },
  {
    rel: "node_modules/@earendil-works/pi-agent-core/dist/harness/tools/edit.js",
    applied: EDIT_REPAIR_APPLIED,
    find:
      "            if (Array.isArray(parsed))\n" +
      "                args.edits = parsed;\n" +
      "        }\n" +
      "        catch { }\n" +
      "    }\n" +
      "    const legacy = args;",
    replace:
      "            if (Array.isArray(parsed))\n" +
      "                args.edits = parsed;\n" +
      "        }\n" +
      "        " + editRepairCatch(8) + "\n" +
      "    }\n" +
      "    const legacy = args;",
  },
];

export const PATCHES = [ABORT_MARKER_PATCH, ...EDIT_REPAIR_PATCHES];

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
