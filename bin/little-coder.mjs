#!/usr/bin/env node
// little-coder launcher.
// Spawns the bundled pi runtime with our AGENTS.md, skills, and every
// custom extension wired in — works from any working directory.

import { spawn } from "node:child_process";
import {
  existsSync,
  mkdirSync,
  readdirSync,
  readFileSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { homedir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { checkForUpdate } from "./update-check.mjs";
import { parseExtraExtensions } from "./extras.mjs";

// ---- 1. Node version preflight (>= 22.19.0, matching pi.dev) ----
const MIN_NODE = [22, 19, 0];
const cur = process.versions.node.split(".").map((n) => parseInt(n, 10));
const tooOld =
  cur[0] < MIN_NODE[0] ||
  (cur[0] === MIN_NODE[0] && cur[1] < MIN_NODE[1]) ||
  (cur[0] === MIN_NODE[0] && cur[1] === MIN_NODE[1] && cur[2] < MIN_NODE[2]);
if (tooOld) {
  console.error(
    `little-coder requires Node.js >= ${MIN_NODE.join(".")} (you have ${process.versions.node}).\n` +
      `Install a newer Node from https://nodejs.org or via nvm: 'nvm install 22'.`,
  );
  process.exit(1);
}

// ---- 2. Resolve package install root ----
const here = dirname(fileURLToPath(import.meta.url));
const pkgRoot = resolve(here, "..");

// Headless sub-coder fast-path. When the subagent extension re-invokes this
// launcher to spawn a child little-coder (--mode json -p), the update check and
// the global-settings merge below are pointless per-child overhead (network +
// disk) — and we want children to start fast. The env flag is set by
// .pi/extensions/subagent/spawn.ts::buildChildEnv.
const isSubagent = process.env.LITTLE_CODER_SUBAGENT === "1";

// ---- 3. Resolve the bundled pi CLI entry point ----
// We invoke pi's JS entry directly under the current Node binary instead of
// the `node_modules/.bin/pi` shim. Two reasons:
//   1. On Windows, `.bin/pi.cmd` is an npm-generated batch shim. When it (or
//      anything it transitively invokes) is launched from a path containing
//      spaces — most notably the default Node install location
//      `C:\Program Files\nodejs\` — cmd's whitespace tokenization can split
//      the path at the first space and produce errors like
//      `'C:\Program' is not recognized as an internal or external command`
//      (see issue #23). Spawning `process.execPath` with the resolved cli.js
//      path as an argv element sidesteps cmd entirely — Node's spawn handles
//      Windows argv quoting itself.
//   2. We no longer need a separate `cmd.exe /c …` branch, so the same
//      spawn path works identically on Linux, macOS, and Windows.
const piPkgRoot = join(pkgRoot, "node_modules", "@earendil-works", "pi-coding-agent");
let piEntry;
try {
  const piPkgJson = JSON.parse(readFileSync(join(piPkgRoot, "package.json"), "utf-8"));
  const binRel = typeof piPkgJson?.bin === "string" ? piPkgJson.bin : piPkgJson?.bin?.pi;
  if (typeof binRel !== "string") throw new Error("pi package.json has no bin.pi entry");
  piEntry = resolve(piPkgRoot, binRel);
} catch (err) {
  console.error(
    `little-coder: cannot resolve pi cli entry under ${piPkgRoot}.\n` +
      `Underlying error: ${err?.message ?? err}\n` +
      `Try reinstalling: npm install -g little-coder`,
  );
  process.exit(1);
}
if (!existsSync(piEntry)) {
  console.error(
    `little-coder: cannot find pi at ${piEntry}.\n` +
      `Try reinstalling: npm install -g little-coder`,
  );
  process.exit(1);
}

// ---- 3b. Re-apply little-coder's pi-runtime patches (best-effort) ----
// pi is a normal dependency, so we can't ship a modified copy; instead we
// re-apply small source edits (e.g. suppressing pi's bare "Operation aborted"
// marker) on every launch. This self-heals when npm install scripts were
// skipped or pi was reinstalled. Cosmetic only — never block launch.
try {
  const { applyPiPatches } = await import("../scripts/patch-pi.mjs");
  applyPiPatches(piPkgRoot);
} catch {
  // patches are non-essential; ignore (missing file, read-only FS, etc.)
}

// ---- 4. Auto-discover bundled extensions ----
const extDir = join(pkgRoot, ".pi", "extensions");
const extArgs = [];
if (existsSync(extDir)) {
  for (const name of readdirSync(extDir).sort()) {
    const subdir = join(extDir, name);
    const idx = join(subdir, "index.ts");
    try {
      if (statSync(subdir).isDirectory() && existsSync(idx)) {
        extArgs.push("--extension", idx);
      }
    } catch {
      // skip unreadable entries
    }
  }
}

// ---- 4b. Third-party extensions via LITTLE_CODER_EXTRA_EXTENSIONS ----
// Path-delimited list (`:` on POSIX, `;` on Windows — node:path.delimiter)
// of extra extension paths to load alongside the bundled ones. Each entry can
// be either a direct file path (e.g. a pi-ponytail-style `extensions/ponytail.js`)
// or a directory containing `index.ts` / `index.js`. Survives upgrades and
// avoids the "fork the installed npm package" workaround that issue #46 hit.
// Parsing rules — ~/ expansion, directory-with-index resolution, one-line
// warning for missing/unusable entries — live in ./extras.mjs so they're
// unit-testable in isolation.
{
  const { entries, warnings } = parseExtraExtensions(process.env.LITTLE_CODER_EXTRA_EXTENSIONS);
  for (const w of warnings) console.error(w);
  for (const entry of entries) extArgs.push("--extension", entry);
}

// ---- 5. Update check (best-effort, blocks on TTY prompt only) ----
let currentVersion = "0.0.0";
try {
  const pkgJson = JSON.parse(readFileSync(join(pkgRoot, "package.json"), "utf-8"));
  if (typeof pkgJson?.version === "string") currentVersion = pkgJson.version;
} catch {
  // ignore — update-check just won't fire if we can't read the version
}
if (!isSubagent) {
  const forceUpdate = process.argv.includes("--update");
  const exitAfterCheck = await checkForUpdate(currentVersion, { force: forceUpdate });
  if (exitAfterCheck) {
    // Successful update happened; user needs to re-run the new binary.
    process.exit(0);
  }
}

// ---- 6. Compose pi argv ----
// --no-context-files : ignore the user's AGENTS.md / CLAUDE.md so OURS wins
// --no-extensions    : skip pi's auto-discovery from cwd; explicit -e flags still load
// --system-prompt    : load <pkgRoot>/AGENTS.md regardless of cwd
//
// Strip our own flags before forwarding to pi so it doesn't reject them.
const userArgs = process.argv.slice(2).filter(
  (a) => a !== "--no-update-check" && a !== "--update",
);
const agentsMd = join(pkgRoot, "AGENTS.md");

// Default the thinking level to "medium" for interactive sessions (pi's own
// default is "minimal"). Only when the user hasn't asked for a level themselves
// (--thinking, or the --model "provider/id:level" shorthand) and this isn't a
// headless/sub-coder run (--mode rpc/json) where the caller controls thinking.
const userPickedThinking =
  userArgs.includes("--thinking") ||
  userArgs.some((a, i) => a === "--model" && /:/.test(userArgs[i + 1] || ""));
const headless = isSubagent || userArgs.includes("--mode") || userArgs.includes("-p");
const thinkingArgs = !userPickedThinking && !headless ? ["--thinking", "medium"] : [];

const piArgs = [
  "--no-context-files",
  "--no-extensions",
  ...(existsSync(agentsMd) ? ["--system-prompt", agentsMd] : []),
  ...thinkingArgs,
  ...extArgs,
  ...userArgs,
];

// ---- 7. Suppress pi's own version-banner by default ----
// pi is an internal dependency here; users install `little-coder` and shouldn't
// see in-session nags about updating the underlying coding-agent package.
// PI_SKIP_VERSION_CHECK is the surgical pi switch (interactive-mode.js:525)
// that gates the "Update Available" banner without touching pi's other
// network-dependent startup paths. Honor an explicit user value (set to "0" or
// anything else to re-enable the banner; PI_OFFLINE=1 also re-overrides).
if (process.env.PI_SKIP_VERSION_CHECK === undefined) {
  process.env.PI_SKIP_VERSION_CHECK = "1";
}

// ---- 8. Force pi's global quietStartup + pin lastChangelogVersion ----
// Two non-destructive merges into ~/.pi/agent/settings.json (or the dir pointed
// to by PI_CODING_AGENT_DIR):
//
//   1. quietStartup: true
//        Pi's interactive mode otherwise dumps an [Extensions] / [Skills] /
//        [Prompts] inventory on every launch. Pi reads global settings from
//        <agentDir>/settings.json — NOT from our npm-installed package dir —
//        so our shipped .pi/settings.json doesn't reach it. To see the
//        inventory anyway, run `little-coder --verbose`.
//
//   2. lastChangelogVersion: <currently installed pi version>
//        Pi reads its own bundled CHANGELOG.md on startup and renders a
//        "What's New" block for every entry strictly newer than this stored
//        version (interactive-mode.js:getChangelogForDisplay). That makes pi's
//        upstream changelog show up inside little-coder's TUI every time we
//        bump the bundled pi dep — which is jarring because little-coder is
//        the surface, not pi. We pre-stamp this field to the version we just
//        bundled BEFORE pi starts, so pi sees "user already saw this", and
//        the block never renders. Users who genuinely want to read pi's
//        upstream changelog can still do so with `/changelog` inside the TUI.
//
// Existing keys are preserved. We only write when the desired value differs
// from what's already on disk, so this is a no-op on warm launches.
//
// Skipped for headless sub-coders: they share the user's settings (already
// written by the interactive parent) and shouldn't each re-do the merge.
if (!isSubagent) try {
  const agentDirEnv = process.env.PI_CODING_AGENT_DIR;
  let agentDir;
  if (agentDirEnv && agentDirEnv.trim().length > 0) {
    agentDir = agentDirEnv === "~"
      ? homedir()
      : agentDirEnv.startsWith("~/")
        ? homedir() + agentDirEnv.slice(1)
        : agentDirEnv;
  } else {
    agentDir = join(homedir(), ".pi", "agent");
  }
  mkdirSync(agentDir, { recursive: true });
  const globalSettingsPath = join(agentDir, "settings.json");
  let globalSettings = {};
  if (existsSync(globalSettingsPath)) {
    try {
      const parsed = JSON.parse(readFileSync(globalSettingsPath, "utf-8"));
      if (parsed && typeof parsed === "object") globalSettings = parsed;
    } catch {
      // Corrupted JSON — start fresh rather than throw. Pi would have rejected it too.
      globalSettings = {};
    }
  }

  // Read the bundled pi version. We resolve via the same package.json we used
  // to find piEntry, so this stays consistent with whichever pi we actually
  // spawn — no second source of truth.
  let bundledPiVersion;
  try {
    const piPkgJson = JSON.parse(
      readFileSync(join(piPkgRoot, "package.json"), "utf-8"),
    );
    if (typeof piPkgJson?.version === "string") bundledPiVersion = piPkgJson.version;
  } catch {
    // If we can't read pi's version, fall back to leaving lastChangelogVersion
    // alone — pi will then show its own changelog on the next launch. Better
    // than writing garbage into the user's settings.
  }

  let mutated = false;
  if (globalSettings.quietStartup !== true) {
    globalSettings.quietStartup = true;
    mutated = true;
  }
  if (bundledPiVersion && globalSettings.lastChangelogVersion !== bundledPiVersion) {
    globalSettings.lastChangelogVersion = bundledPiVersion;
    mutated = true;
  }
  if (mutated) {
    writeFileSync(globalSettingsPath, JSON.stringify(globalSettings, null, 2));
  }

  // ---- 8b. One-time cleanup of the v1.9.0 keybinding rewrite ----
  // v1.9.0 wrote `app.thinking.cycle: "alt+t"` into ~/.pi/agent/keybindings.json
  // so the plan-mode extension could claim shift+tab (issue #47). Plan mode now
  // lives on alt+p, so shift+tab should go back to pi's default thinking-cycle
  // binding — but only if the value is *exactly* the one we wrote. A user who
  // chose their own binding (anything ≠ "alt+t") wins.
  const keybindingsPath = join(agentDir, "keybindings.json");
  if (existsSync(keybindingsPath)) {
    try {
      const parsed = JSON.parse(readFileSync(keybindingsPath, "utf-8"));
      if (parsed && typeof parsed === "object" && parsed["app.thinking.cycle"] === "alt+t") {
        delete parsed["app.thinking.cycle"];
        if (Object.keys(parsed).length === 0) {
          // Don't leave an empty {} sitting around — remove the file so pi
          // reads its defaults cleanly.
          rmSync(keybindingsPath);
        } else {
          writeFileSync(keybindingsPath, JSON.stringify(parsed, null, 2));
        }
      }
    } catch {
      // Corrupted JSON or unreadable — leave it alone; pi will surface its own error.
    }
  }

} catch {
  // Best-effort. If we can't write the settings (read-only HOME, etc.) pi
  // falls back to its built-in defaults — the [Extensions] block will show
  // but everything else still works.
}

// ---- 9. Spawn pi in the user's cwd ----
// `process.execPath` is the same Node binary that's running this launcher, so
// pi inherits the exact runtime that already passed our >= 22.19.0 preflight.
// Passing piEntry as an argv element (not a shell string) avoids any
// shell-injection / space-in-path classes on every platform.
const child = spawn(process.execPath, [piEntry, ...piArgs], {
  stdio: "inherit",
  cwd: process.cwd(),
  env: process.env,
});

const forward = (sig) => () => {
  try {
    child.kill(sig);
  } catch {
    // child already gone
  }
};
process.on("SIGINT", forward("SIGINT"));
process.on("SIGTERM", forward("SIGTERM"));
process.on("SIGHUP", forward("SIGHUP"));

child.on("error", (err) => {
  console.error("little-coder: failed to start pi:", err.message);
  process.exit(1);
});

child.on("exit", (code, signal) => {
  if (signal) {
    process.kill(process.pid, signal);
  } else {
    process.exit(code ?? 0);
  }
});
