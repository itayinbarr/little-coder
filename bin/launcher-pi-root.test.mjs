import { describe, expect, it } from "vitest";
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { PATCHES } from "../scripts/patch-pi.mjs";

// Regression tests for the `piPkgRoot` scope bug.
//
// The launcher resolves pi's package root in a `for (const … of piPkgCandidates)`
// loop, then needs that root twice more further down: once to apply our pi
// runtime patches (step 3b) and once to read pi's version so it can pin
// `lastChangelogVersion` (step 8). A `for (const …)` binding is scoped to the
// loop body, so referencing it below threw `ReferenceError` — and because both
// call sites sit inside best-effort try/catch blocks, the failure was silent:
// pi went unpatched, and pi's own "What's New" changelog rendered inside the
// little-coder TUI after every pi version bump.
//
// Both tests exercise the real launcher end to end, so they catch the binding
// being re-scoped into the loop no matter how it's spelled.

const here = dirname(fileURLToPath(import.meta.url));
const pkgRoot = resolve(here, "..");
const launcher = join(pkgRoot, "bin", "little-coder.mjs");
const piPkgRoot = join(pkgRoot, "node_modules", "@earendil-works", "pi-coding-agent");

/** Run the launcher with an isolated pi agent dir. `--version` exits fast. */
function runLauncher(agentDir) {
  execFileSync(process.execPath, [launcher, "--no-update-check", "--version"], {
    cwd: pkgRoot,
    env: { ...process.env, PI_CODING_AGENT_DIR: agentDir },
    stdio: "ignore",
    timeout: 60_000,
  });
}

describe("launcher resolves pi's package root for every consumer", () => {
  it("pins lastChangelogVersion to the bundled pi version", () => {
    const agentDir = mkdtempSync(join(tmpdir(), "lc-agentdir-"));
    try {
      runLauncher(agentDir);
      const settings = JSON.parse(readFileSync(join(agentDir, "settings.json"), "utf-8"));
      const piVersion = JSON.parse(
        readFileSync(join(piPkgRoot, "package.json"), "utf-8"),
      ).version;

      // The bug's signature: quietStartup was written (it needs no pi root) but
      // lastChangelogVersion was absent, so pi replayed its upstream changelog
      // into our TUI on the next launch.
      expect(settings.quietStartup).toBe(true);
      expect(settings.lastChangelogVersion).toBe(piVersion);
    } finally {
      rmSync(agentDir, { recursive: true, force: true });
    }
  });

  it("applies the pi runtime patches on launch", () => {
    const patch = PATCHES[0];
    const file = join(piPkgRoot, patch.rel);
    const original = readFileSync(file, "utf-8");

    // Only meaningful while pi still ships the shape this patch targets. If pi
    // changes it, the patcher skips silently by design and there's nothing to
    // assert — that's a signal to refresh the patch, not a launcher regression.
    if (!original.includes(patch.applied)) return;

    const agentDir = mkdtempSync(join(tmpdir(), "lc-agentdir-"));
    try {
      // Reverse the patch so the launch has real work to do.
      writeFileSync(file, original.replace(patch.replace, patch.find));
      expect(readFileSync(file, "utf-8")).not.toContain(patch.applied);

      runLauncher(agentDir);

      expect(readFileSync(file, "utf-8")).toContain(patch.applied);
    } finally {
      writeFileSync(file, original);
      rmSync(agentDir, { recursive: true, force: true });
    }
  });
});
