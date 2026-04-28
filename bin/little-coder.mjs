#!/usr/bin/env node
// little-coder launcher.
// Spawns the bundled pi runtime with our AGENTS.md, skills, and every
// custom extension wired in — works from any working directory.

import { spawn } from "node:child_process";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { checkForUpdate } from "./update-check.mjs";

// ---- 1. Node version preflight (>= 20.6.0, matching pi.dev) ----
const MIN_NODE = [20, 6, 0];
const cur = process.versions.node.split(".").map((n) => parseInt(n, 10));
const tooOld =
  cur[0] < MIN_NODE[0] ||
  (cur[0] === MIN_NODE[0] && cur[1] < MIN_NODE[1]) ||
  (cur[0] === MIN_NODE[0] && cur[1] === MIN_NODE[1] && cur[2] < MIN_NODE[2]);
if (tooOld) {
  console.error(
    `little-coder requires Node.js >= ${MIN_NODE.join(".")} (you have ${process.versions.node}).\n` +
      `Install a newer Node from https://nodejs.org or via nvm: 'nvm install 20'.`,
  );
  process.exit(1);
}

// ---- 2. Resolve package install root ----
const here = dirname(fileURLToPath(import.meta.url));
const pkgRoot = resolve(here, "..");

// ---- 3. Resolve the bundled pi binary ----
const piBin = join(pkgRoot, "node_modules", ".bin", "pi");
if (!existsSync(piBin)) {
  console.error(
    `little-coder: cannot find pi at ${piBin}.\n` +
      `Try reinstalling: npm install -g little-coder`,
  );
  process.exit(1);
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

// ---- 5. Update check (best-effort, blocks on TTY prompt only) ----
let currentVersion = "0.0.0";
try {
  const pkgJson = JSON.parse(readFileSync(join(pkgRoot, "package.json"), "utf-8"));
  if (typeof pkgJson?.version === "string") currentVersion = pkgJson.version;
} catch {
  // ignore — update-check just won't fire if we can't read the version
}
const exitAfterCheck = await checkForUpdate(currentVersion);
if (exitAfterCheck) {
  // Successful update happened; user needs to re-run the new binary.
  process.exit(0);
}

// ---- 6. Compose pi argv ----
// --no-context-files : ignore the user's AGENTS.md / CLAUDE.md so OURS wins
// --no-extensions    : skip pi's auto-discovery from cwd; explicit -e flags still load
// --system-prompt    : load <pkgRoot>/AGENTS.md regardless of cwd
//
// Strip our own flags before forwarding to pi so it doesn't reject them.
const userArgs = process.argv.slice(2).filter((a) => a !== "--no-update-check");
const agentsMd = join(pkgRoot, "AGENTS.md");
const piArgs = [
  "--no-context-files",
  "--no-extensions",
  ...(existsSync(agentsMd) ? ["--system-prompt", agentsMd] : []),
  ...extArgs,
  ...userArgs,
];

// ---- 7. Spawn pi in the user's cwd ----
const child = spawn(piBin, piArgs, {
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
