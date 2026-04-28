// little-coder update check.
// Polls the npm registry for a newer published version and (in TTY mode)
// offers to install it before the agent starts. Cached so we don't call out
// on every invocation. Best-effort throughout: if anything fails, we skip
// silently — never block the agent over a version check.

import { existsSync, mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, join } from "node:path";
import { spawnSync } from "node:child_process";
import { createInterface } from "node:readline";

const REGISTRY = "https://registry.npmjs.org/little-coder/latest";
const CACHE_TTL_MS = 12 * 60 * 60 * 1000;   // 12 h
const FETCH_TIMEOUT_MS = 2000;

export function cachePath() {
  const xdg = process.env.XDG_CACHE_HOME && process.env.XDG_CACHE_HOME.trim();
  const base = xdg ? xdg : join(homedir(), ".cache");
  return join(base, "little-coder", "version-check.json");
}

export function readCache(now = Date.now()) {
  try {
    const path = cachePath();
    if (!existsSync(path)) return null;
    const data = JSON.parse(readFileSync(path, "utf-8"));
    if (typeof data.checkedAt !== "number" || typeof data.latest !== "string") return null;
    if (now - data.checkedAt > CACHE_TTL_MS) return null;
    return data;
  } catch {
    return null;
  }
}

export function writeCache(latest, now = Date.now()) {
  try {
    const path = cachePath();
    mkdirSync(dirname(path), { recursive: true });
    writeFileSync(path, JSON.stringify({ checkedAt: now, latest }));
  } catch {
    // best-effort; permission errors etc. are not fatal
  }
}

// Compare semver strings. Only handles X.Y.Z[+pre]. Returns 1 if a > b,
// -1 if a < b, 0 if equal. Pre-release suffixes are treated as < release.
export function compareSemver(a, b) {
  const parse = (v) => {
    const [core, pre] = String(v).split("-", 2);
    const parts = core.split(".").map((n) => parseInt(n, 10));
    return {
      major: parts[0] || 0,
      minor: parts[1] || 0,
      patch: parts[2] || 0,
      pre: pre || "",
    };
  };
  const pa = parse(a);
  const pb = parse(b);
  if (pa.major !== pb.major) return pa.major > pb.major ? 1 : -1;
  if (pa.minor !== pb.minor) return pa.minor > pb.minor ? 1 : -1;
  if (pa.patch !== pb.patch) return pa.patch > pb.patch ? 1 : -1;
  // Equal core: a release beats a pre-release.
  if (pa.pre === pb.pre) return 0;
  if (pa.pre === "") return 1;
  if (pb.pre === "") return -1;
  return pa.pre > pb.pre ? 1 : -1;
}

async function fetchLatest() {
  const ctrl = new AbortController();
  const t = setTimeout(() => ctrl.abort(), FETCH_TIMEOUT_MS);
  try {
    const res = await fetch(REGISTRY, { signal: ctrl.signal });
    if (!res.ok) return null;
    const json = await res.json();
    return typeof json?.version === "string" ? json.version : null;
  } catch {
    return null;
  } finally {
    clearTimeout(t);
  }
}

// Decide whether to skip the check entirely. Errs toward NOT prompting in
// any context that smells programmatic.
export function shouldSkip(argv = process.argv.slice(2), env = process.env, stdout = process.stdout) {
  if (env.LITTLE_CODER_NO_UPDATE_CHECK === "1") return true;
  if (env.CI === "true" || env.CI === "1") return true;
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--no-update-check") return true;
    if (a === "--help" || a === "-h") return true;
    if (a === "--version" || a === "-v") return true;
    if (a === "--list-models") return true;
    if (a === "--export") return true;
    if (a === "--mode") {
      const next = argv[i + 1];
      if (next === "rpc" || next === "json") return true;
    }
  }
  // Non-TTY runs: scripts, pipes, --print pipelines. Notice only, no prompt.
  if (!stdout.isTTY) return "notice-only";
  return false;
}

function promptYesNo(question) {
  return new Promise((resolve) => {
    if (!process.stdin.isTTY) {
      resolve(false);
      return;
    }
    const rl = createInterface({ input: process.stdin, output: process.stderr });
    rl.question(question, (answer) => {
      rl.close();
      const a = (answer ?? "").trim().toLowerCase();
      resolve(a === "" || a === "y" || a === "yes");
    });
  });
}

// Returns `true` if the launcher should NOT proceed to spawn pi (because we
// updated and exited / the user opted out and we should re-run).  Returns
// `false` to let the launcher continue.
export async function checkForUpdate(currentVersion, opts = {}) {
  const skip = opts.skip ?? shouldSkip();
  if (skip === true) return false;

  let latest = readCache()?.latest;
  if (!latest) {
    latest = await fetchLatest();
    if (latest) writeCache(latest);
  }
  if (!latest) return false;
  if (compareSemver(latest, currentVersion) <= 0) return false;

  const headline =
    `\n📦 little-coder v${latest} is available (you have v${currentVersion}).`;

  if (skip === "notice-only") {
    process.stderr.write(`${headline}\n   Update with: npm install -g little-coder\n\n`);
    return false;
  }

  process.stderr.write(`${headline}\n`);
  const wantsUpdate = await promptYesNo("   Update now? [Y/n] ");
  if (!wantsUpdate) {
    process.stderr.write("   Skipping update for this run.\n\n");
    return false;
  }

  process.stderr.write(`\n   Running: npm install -g little-coder@${latest}\n\n`);
  const result = spawnSync("npm", ["install", "-g", `little-coder@${latest}`], {
    stdio: "inherit",
  });
  if (result.status === 0) {
    process.stderr.write(
      `\n   ✓ Updated to v${latest}. Re-run \`little-coder\` to use the new version.\n\n`,
    );
    return true;
  }
  process.stderr.write(
    `\n   ✗ Update failed (npm exit ${result.status}). Continuing with v${currentVersion}.\n\n`,
  );
  return false;
}
