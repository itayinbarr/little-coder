import { describe, expect, it } from "vitest";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { discoverUserExtensions, resolveUserExtensionsDir } from "./user-extensions.mjs";

const HOME = "/home/me";

describe("resolveUserExtensionsDir", () => {
  it("prefers an explicit LITTLE_CODER_EXTENSIONS_DIR", () => {
    expect(
      resolveUserExtensionsDir({ LITTLE_CODER_EXTENSIONS_DIR: "/opt/ext" }, HOME),
    ).toBe("/opt/ext");
  });

  it("expands ~ in the explicit path", () => {
    expect(
      resolveUserExtensionsDir({ LITTLE_CODER_EXTENSIONS_DIR: "~/ext" }, HOME),
    ).toBe("/home/me/ext");
    expect(resolveUserExtensionsDir({ LITTLE_CODER_EXTENSIONS_DIR: "~" }, HOME)).toBe(HOME);
  });

  it("falls back to XDG_CONFIG_HOME, then ~/.config", () => {
    expect(resolveUserExtensionsDir({ XDG_CONFIG_HOME: "/xdg" }, HOME)).toBe(
      "/xdg/little-coder/extensions",
    );
    expect(resolveUserExtensionsDir({ HOME }, HOME)).toBe(
      "/home/me/.config/little-coder/extensions",
    );
  });

  it("ignores a blank explicit value rather than resolving to nothing", () => {
    expect(resolveUserExtensionsDir({ LITTLE_CODER_EXTENSIONS_DIR: "   ", HOME }, HOME)).toBe(
      "/home/me/.config/little-coder/extensions",
    );
  });
});

describe("discoverUserExtensions", () => {
  /** Build a real directory so we exercise the actual fs calls. */
  function withDir(build) {
    const root = mkdtempSync(join(tmpdir(), "lc-userext-"));
    try {
      build(root);
      return { root, ...discoverUserExtensions({ LITTLE_CODER_EXTENSIONS_DIR: root }) };
    } finally {
      // Caller only inspects the returned value; clean up immediately.
      rmSync(root, { recursive: true, force: true });
    }
  }

  it("is a silent no-op when the directory does not exist", () => {
    // The common case by far — this must cost nothing and say nothing.
    const result = discoverUserExtensions({
      LITTLE_CODER_EXTENSIONS_DIR: join(tmpdir(), "definitely-not-here-lc"),
    });
    expect(result.entries).toEqual([]);
    expect(result.warnings).toEqual([]);
  });

  it("loads bare .ts/.js/.mjs files", () => {
    const { root, entries } = withDir((d) => {
      writeFileSync(join(d, "alpha.ts"), "export default () => {};");
      writeFileSync(join(d, "beta.js"), "export default () => {};");
      writeFileSync(join(d, "gamma.mjs"), "export default () => {};");
    });
    expect(entries).toEqual([
      join(root, "alpha.ts"),
      join(root, "beta.js"),
      join(root, "gamma.mjs"),
    ]);
  });

  it("resolves a directory to its index.ts, preferring .ts over .js", () => {
    const { root, entries } = withDir((d) => {
      mkdirSync(join(d, "mine"));
      writeFileSync(join(d, "mine", "index.js"), "");
      writeFileSync(join(d, "mine", "index.ts"), "");
    });
    expect(entries).toEqual([join(root, "mine", "index.ts")]);
  });

  it("warns and skips a directory with no entry point", () => {
    const { entries, warnings } = withDir((d) => {
      mkdirSync(join(d, "broken"));
      writeFileSync(join(d, "broken", "helper.ts"), "");
    });
    expect(entries).toEqual([]);
    expect(warnings).toHaveLength(1);
    expect(warnings[0]).toContain("no index.ts/index.js");
  });

  it("warns about a file that could never be an extension", () => {
    const { warnings } = withDir((d) => {
      writeFileSync(join(d, "notes.py"), "");
    });
    expect(warnings).toHaveLength(1);
    expect(warnings[0]).toContain("need .ts/.js/.mjs");
  });

  it("stays quiet about housekeeping files", () => {
    // Installing a dependency in there shouldn't produce a wall of warnings.
    const { entries, warnings } = withDir((d) => {
      writeFileSync(join(d, "README.md"), "");
      writeFileSync(join(d, "package.json"), "{}");
      writeFileSync(join(d, "package-lock.json"), "{}");
      writeFileSync(join(d, ".gitignore"), "");
      mkdirSync(join(d, "node_modules"));
      mkdirSync(join(d, ".git"));
    });
    expect(entries).toEqual([]);
    expect(warnings).toEqual([]);
  });

  it("loads entries in a stable, sorted order", () => {
    const { root, entries } = withDir((d) => {
      writeFileSync(join(d, "zulu.ts"), "");
      writeFileSync(join(d, "alpha.ts"), "");
      writeFileSync(join(d, "mike.ts"), "");
    });
    expect(entries).toEqual([
      join(root, "alpha.ts"),
      join(root, "mike.ts"),
      join(root, "zulu.ts"),
    ]);
  });

  it("reports the resolved directory even when empty, for the /extensions hint", () => {
    const { root, dir } = withDir(() => {});
    expect(dir).toBe(root);
  });
});
