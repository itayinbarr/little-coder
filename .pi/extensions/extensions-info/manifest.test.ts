import { describe, expect, it } from "vitest";
import { extensionLabel, panelLines, parseManifest, tildify } from "./manifest.ts";
import { visibleWidth } from "../_shared/width.ts";

const full = {
  bundled: ["/pkg/.pi/extensions/branding/index.ts", "/pkg/.pi/extensions/write-guard/index.ts"],
  env: ["/opt/pi-ponytail/extensions/ponytail.js"],
  user: ["/home/me/.config/little-coder/extensions/telegram.ts"],
  userDir: "/home/me/.config/little-coder/extensions",
  userDirExists: true,
  warnings: ["little-coder: user extension has no index.ts/index.js, skipping: /x/broken"],
  piDiscovery: false,
};

describe("parseManifest", () => {
  it("round-trips what the launcher serializes", () => {
    expect(parseManifest(JSON.stringify(full))).toEqual(full);
  });

  it("degrades to an empty manifest rather than throwing", () => {
    // /extensions saying "nothing recorded" beats it crashing the TUI.
    for (const raw of [undefined, "", "not json", "null", "[]", '"a string"', "7"]) {
      const m = parseManifest(raw as string | undefined);
      expect(m.bundled).toEqual([]);
      expect(m.warnings).toEqual([]);
      expect(m.piDiscovery).toBe(false);
    }
  });

  it("drops non-string entries instead of trusting the payload", () => {
    const m = parseManifest(JSON.stringify({ bundled: ["ok", 3, null, { a: 1 }] }));
    expect(m.bundled).toEqual(["ok"]);
  });
});

describe("extensionLabel", () => {
  it("names a directory extension after its directory", () => {
    expect(extensionLabel("/pkg/.pi/extensions/write-guard/index.ts")).toBe("write-guard");
    expect(extensionLabel("/x/mine/index.js")).toBe("mine");
  });
  it("names a single-file extension after the file", () => {
    expect(extensionLabel("/x/ponytail.js")).toBe("ponytail.js");
  });
});

describe("tildify", () => {
  it("shortens paths under home", () => {
    expect(tildify("/home/me/.config/lc/e.ts", "/home/me")).toBe("~/.config/lc/e.ts");
  });
  it("leaves other paths alone", () => {
    expect(tildify("/opt/e.ts", "/home/me")).toBe("/opt/e.ts");
    expect(tildify("/opt/e.ts", undefined)).toBe("/opt/e.ts");
  });
});

describe("panelLines", () => {
  const text = (m: any, width = 120) => panelLines(m, width, "/home/me").join("\n");

  it("counts bundled extensions and lists the user's by path", () => {
    const out = text(full);
    expect(out).toContain("bundled");
    expect(out).toContain("2");
    expect(out).toContain("~/.config/little-coder/extensions/telegram.ts");
  });

  it("tells the user where to put an extension when they have none", () => {
    // This is the discoverability fix — an empty list must still teach.
    const out = text({ ...full, user: [], userDirExists: false });
    expect(out).toContain("drop a .ts/.js file in ~/.config/little-coder/extensions");
  });

  it("states whether pi's own discovery is on, and how to turn it on", () => {
    expect(text(full)).toContain("--with-pi-extensions");
    expect(text({ ...full, piDiscovery: true })).toContain("pi's own extensions are loading");
  });

  it("surfaces load failures", () => {
    const out = text(full);
    expect(out).toContain("no index.ts/index.js");
    // The "little-coder:" prefix is redundant inside little-coder's own panel.
    expect(out).not.toContain("little-coder: user extension");
  });

  it("omits the env section entirely when unused", () => {
    expect(text({ ...full, env: [] })).not.toContain("LITTLE_CODER_EXTRA_EXTENSIONS");
    expect(text(full)).toContain("LITTLE_CODER_EXTRA_EXTENSIONS");
  });

  it("fits inside pi's 10-line widget cap", () => {
    const many = {
      ...full,
      user: Array.from({ length: 20 }, (_, i) => `/home/me/.config/little-coder/extensions/e${i}.ts`),
      env: Array.from({ length: 5 }, (_, i) => `/opt/env${i}.js`),
    };
    for (const m of [full, many, { ...full, user: [] }]) {
      expect(panelLines(m, 120, "/home/me").length).toBeLessThanOrEqual(10);
    }
  });

  it("drops individual paths before it drops a section or an error", () => {
    // The counts, the pi-discovery state and the load errors are the rows that
    // matter; a long list of paths is what should give way.
    const many = {
      ...full,
      user: Array.from({ length: 20 }, (_, i) => `/home/me/.config/little-coder/extensions/e${i}.ts`),
    };
    const out = panelLines(many, 120, "/home/me").join("\n");
    expect(out).toContain("bundled");
    expect(out).toContain("yours");
    expect(out).toContain("pi extensions");
    expect(out).toContain("no index.ts/index.js"); // the warning survived
    expect(out).toMatch(/\+\d+ more/); // and the overflow is acknowledged
  });

  it("never emits a line wider than the terminal (issue #48 safety)", () => {
    for (const width of [20, 30, 40, 80, 120]) {
      for (const line of panelLines(full, width, "/home/me")) {
        expect(visibleWidth(line)).toBeLessThanOrEqual(width);
      }
    }
  });

  it("renders an empty manifest without throwing", () => {
    expect(() => panelLines(parseManifest(undefined), 80, "/home/me")).not.toThrow();
  });
});
