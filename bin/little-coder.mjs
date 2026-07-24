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
import { discoverUserExtensions } from "./user-extensions.mjs";
import { resolveConfiguredDefault, decideDefaultModel } from "./default-model.mjs";

// Resolve pi's agent directory (where it persists settings.json / keybindings).
// Honors PI_CODING_AGENT_DIR (with ~ expansion), else ~/.pi/agent. Shared by the
// default-model detection (issue #65) and the global-settings merge below.
function resolveAgentDir() {
  const agentDirEnv = process.env.PI_CODING_AGENT_DIR;
  if (agentDirEnv && agentDirEnv.trim().length > 0) {
    if (agentDirEnv === "~") return homedir();
    if (agentDirEnv.startsWith("~/")) return homedir() + agentDirEnv.slice(1);
    return agentDirEnv;
  }
  return join(homedir(), ".pi", "agent");
}

// Best-effort JSON read: returns the parsed object or undefined on any failure.
function readJsonSafe(path) {
  try {
    return JSON.parse(readFileSync(path, "utf-8"));
  } catch {
    return undefined;
  }
}

// User models.json override path, mirroring llama-cpp-provider/config.ts's
// resolution order (LITTLE_CODER_MODELS_FILE → XDG → ~/.config).
function resolveUserModelsPath() {
  if (process.env.LITTLE_CODER_MODELS_FILE) return process.env.LITTLE_CODER_MODELS_FILE;
  if (process.env.XDG_CONFIG_HOME) {
    return join(process.env.XDG_CONFIG_HOME, "little-coder", "models.json");
  }
  const home = process.env.HOME || process.env.USERPROFILE;
  if (home) return join(home, ".config", "little-coder", "models.json");
  return undefined;
}

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
// pi can sit in one of two layouts depending on the installer:
//   1. npm `-g` (and local `node_modules`) nests deps under the package:
//      <pkgRoot>/node_modules/@earendil-works/pi-coding-agent
//   2. bun `add -g` hoists deps flat as siblings of the package, so pi lands at
//      <pkgRoot>/../@earendil-works/pi-coding-agent (issue #56).
// Try the npm layout first (the common case), then the bun/flat sibling layout.
const piPkgCandidates = [
  join(pkgRoot, "node_modules", "@earendil-works", "pi-coding-agent"),
  join(dirname(pkgRoot), "@earendil-works", "pi-coding-agent"),
];
let piEntry;
// The pi package root that `piEntry` came from. Declared out here on purpose:
// two later steps need it (the runtime patcher at step 3b and the
// lastChangelogVersion pin at step 8), and a `for (const … of …)` binding is
// scoped to the loop body — referencing it below would throw a ReferenceError
// that the surrounding try/catch would swallow, silently disabling both.
let piPkgRoot;
let piResolveErr;
for (const candidateRoot of piPkgCandidates) {
  try {
    const piPkgJson = JSON.parse(readFileSync(join(candidateRoot, "package.json"), "utf-8"));
    const binRel = typeof piPkgJson?.bin === "string" ? piPkgJson.bin : piPkgJson?.bin?.pi;
    if (typeof binRel !== "string") throw new Error("pi package.json has no bin.pi entry");
    const candidate = resolve(candidateRoot, binRel);
    if (existsSync(candidate)) {
      piEntry = candidate;
      piPkgRoot = candidateRoot;
      break;
    }
    piResolveErr = new Error(`resolved bin ${candidate} does not exist`);
  } catch (err) {
    piResolveErr = err;
  }
}
if (!piEntry) {
  console.error(
    `little-coder: cannot resolve the bundled pi cli. Looked in:\n` +
      piPkgCandidates.map((p) => `  - ${p}`).join("\n") +
      `\nUnderlying error: ${piResolveErr?.message ?? piResolveErr}\n` +
      `Try reinstalling: npm install -g little-coder  (or: bun add -g little-coder)`,
  );
  process.exit(1);
}

// ---- 3b. Apply little-coder's pi-runtime patches (best-effort) ----
// pi is a normal dependency, so we can't ship a modified copy; instead we apply
// small source edits (e.g. suppressing pi's bare "Operation aborted" marker) on
// every launch. This is the ONLY place patching happens — little-coder ships no
// npm install scripts (issue #75), and `/update` installs with --ignore-scripts
// anyway (issue #50), so launch-time is the only moment that reliably runs.
// Patching here also self-heals if pi was reinstalled under us. The patcher is
// idempotent and swallows its own errors; this is cosmetic — never block launch.
try {
  const { applyPiPatches } = await import("../scripts/patch-pi.mjs");
  applyPiPatches(piPkgRoot);
} catch {
  // patches are non-essential; ignore (missing file, read-only FS, etc.)
}

// ---- 4. Auto-discover bundled extensions ----
// Load order matters: bundled first, then the env var, then the user
// directory. pi applies later `--extension` flags after earlier ones, so a
// user extension can override bundled behavior rather than being shadowed by
// it. The three sources are recorded in LITTLE_CODER_EXTENSION_MANIFEST below
// so the `/extensions` command can tell the user where each one came from.
const extDir = join(pkgRoot, ".pi", "extensions");
const extArgs = [];
const loadedBundled = [];
if (existsSync(extDir)) {
  for (const name of readdirSync(extDir).sort()) {
    const subdir = join(extDir, name);
    const idx = join(subdir, "index.ts");
    try {
      if (statSync(subdir).isDirectory() && existsSync(idx)) {
        extArgs.push("--extension", idx);
        loadedBundled.push(idx);
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
const loadedFromEnv = [];
{
  const { entries, warnings } = parseExtraExtensions(process.env.LITTLE_CODER_EXTRA_EXTENSIONS);
  for (const w of warnings) console.error(w);
  for (const entry of entries) {
    extArgs.push("--extension", entry);
    loadedFromEnv.push(entry);
  }
}

// ---- 4c. User extension directory (issues #67, #69) ----
// ~/.config/little-coder/extensions (or $LITTLE_CODER_EXTENSIONS_DIR). Loaded
// if it exists, ignored if it doesn't — an install that never creates it
// behaves exactly as before. This is the discoverable version of 4b: no env
// var to remember, and it survives `npm install -g little-coder@latest`.
const loadedFromUserDir = [];
let userExtensionsDir;
let userExtensionWarnings = [];
{
  const discovered = discoverUserExtensions(process.env);
  userExtensionsDir = discovered.dir;
  userExtensionWarnings = discovered.warnings;
  for (const w of discovered.warnings) console.error(w);
  for (const entry of discovered.entries) {
    extArgs.push("--extension", entry);
    loadedFromUserDir.push(entry);
  }
}

// ---- 4d. Opt-in pi-ecosystem bridge (issue #67) ----
// Off by default, deliberately. `--no-extensions` is why "exactly this set
// loads" holds, and that predictability is a feature on small models. But
// wanting the pi ecosystem too is legitimate, so it's one flag away: with it,
// pi discovers its own extensions from ~/.pi/agent/extensions and
// <cwd>/.pi/extensions as it normally would. Project-local extensions still go
// through pi's own trust prompt before anything runs.
const withPiExtensions =
  process.argv.includes("--with-pi-extensions") || process.env.LITTLE_CODER_PI_EXTENSIONS === "1";

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
    // A successful update just replaced the on-disk launcher with the new
    // version. Instead of exiting and making the user re-type `little-coder`
    // (issue #66), re-exec THIS same launcher path under the current Node — the
    // file on disk is now the updated one, so it loads the new code — passing
    // the user's original args through so they land straight in the new
    // version. We add --no-update-check so the child doesn't re-poll the
    // registry (it's already the latest), which also rules out any relaunch
    // loop. Best-effort: if the re-exec can't start, we fall back to exiting
    // with the manual-relaunch hint that checkForUpdate already printed.
    const passthrough = process.argv
      .slice(2)
      .filter((a) => a !== "--update" && a !== "--no-update-check");
    process.stderr.write("   Relaunching little-coder…\n\n");
    try {
      const relaunch = spawn(
        process.execPath,
        [process.argv[1], "--no-update-check", ...passthrough],
        { stdio: "inherit", cwd: process.cwd(), env: process.env },
      );
      relaunch.on("exit", (code, signal) => {
        if (signal) process.kill(process.pid, signal);
        else process.exit(code ?? 0);
      });
      relaunch.on("error", (err) => {
        process.stderr.write(
          `   Could not relaunch automatically (${err.message}). ` +
            "Run `little-coder` to start the new version.\n",
        );
        process.exit(0);
      });
    } catch (err) {
      process.stderr.write(
        `   Could not relaunch automatically (${err?.message ?? err}). ` +
          "Run `little-coder` to start the new version.\n",
      );
      process.exit(0);
    }
    // Do not fall through to spawning pi from the just-replaced (old) process;
    // the relaunched child owns the session now.
  } else {
    // no update — continue into the normal launch path below
  }
}

// ---- 6. Compose pi argv ----
// --no-context-files : ignore the user's AGENTS.md / CLAUDE.md so OURS wins
// --no-extensions    : skip pi's auto-discovery from cwd; explicit -e flags still
//                      load. Omitted when --with-pi-extensions is on (step 4d).
// --system-prompt    : load <pkgRoot>/AGENTS.md regardless of cwd
//
// Strip our own flags before forwarding to pi so it doesn't reject them.
const userArgs = process.argv.slice(2).filter(
  (a) => a !== "--no-update-check" && a !== "--update" && a !== "--with-pi-extensions",
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

// ---- 6b. Default model on bare launch (issue #65) ----
// If models.json declares a top-level "default": "provider/id" and the user
// neither passed their own --model nor already has a pi-persisted model
// selection, inject that default so `little-coder` with no args just works, and
// print the model's friendly name. First-run-only: once the user picks a model
// in-session (pi persists defaultProvider/defaultModel), we never override it.
// Skipped for headless/sub-coder runs, which set their own model. Best-effort:
// any read/parse failure just leaves pi's own selection behavior unchanged.
const defaultModelArgs = [];
try {
  const configuredDefault = resolveConfiguredDefault(
    readJsonSafe(join(pkgRoot, "models.json")),
    (() => {
      const p = resolveUserModelsPath();
      return p ? readJsonSafe(p) : undefined;
    })(),
  );
  const decision = decideDefaultModel({
    configuredDefault,
    argv: userArgs,
    piSettings: readJsonSafe(join(resolveAgentDir(), "settings.json")),
    headless,
  });
  if (decision) {
    defaultModelArgs.push("--model", decision.ref);
    process.stderr.write(`   ▸ default model: ${decision.name}  (${decision.ref})\n`);
  }
} catch {
  // never block launch over default-model resolution
}

if (withPiExtensions && !isSubagent) {
  process.stderr.write(
    "   ▸ pi extension discovery enabled — pi's own extensions from ~/.pi/agent and\n" +
      "     ./.pi will load alongside little-coder's. The lean, fixed extension set\n" +
      "     (and its small cold-start context) no longer applies.\n",
  );
}

const piArgs = [
  "--no-context-files",
  ...(withPiExtensions ? [] : ["--no-extensions"]),
  ...(existsSync(agentsMd) ? ["--system-prompt", agentsMd] : []),
  ...thinkingArgs,
  ...defaultModelArgs,
  ...extArgs,
  ...userArgs,
];

// Hand the extension inventory to the `/extensions` command inside the TUI.
// The launcher is the only place that knows where each path came from — pi
// sees an undifferentiated list of --extension flags.
process.env.LITTLE_CODER_EXTENSION_MANIFEST = JSON.stringify({
  bundled: loadedBundled,
  env: loadedFromEnv,
  user: loadedFromUserDir,
  userDir: userExtensionsDir ?? null,
  userDirExists: Boolean(userExtensionsDir && existsSync(userExtensionsDir)),
  warnings: userExtensionWarnings,
  piDiscovery: withPiExtensions,
});

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
  const agentDir = resolveAgentDir();
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
