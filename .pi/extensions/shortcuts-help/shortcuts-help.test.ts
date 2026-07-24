import { describe, it, expect } from "vitest";
import { panelLines } from "./index.ts";
import { visibleWidth } from "../_shared/width.ts";

describe("shortcuts-help panelLines", () => {
  it("renders a header plus the little-coder + pi shortcuts", () => {
    const lines = panelLines(80);
    const text = lines.join("\n");
    expect(text).toContain("shortcuts");
    expect(text).toContain("ctrl-q"); // plan mode (little-coder)
    expect(text).toContain("ctrl-h"); // this panel (little-coder)
    expect(text).toContain("/hotkeys"); // pointer to the authoritative list
  });

  it("lists f2 for deep research (issue #74)", () => {
    // The panel exists to make hotkeys discoverable, and deep research — the
    // one flow people ask about — was the one key missing from it.
    const text = panelLines(80).join("\n");
    expect(text).toContain("f2");
    expect(text).toContain("deep research");
  });

  it("does not advertise ctrl-r, which is unbound at the prompt (issue #74)", () => {
    // pi binds "expand / more" to app.tools.expand (ctrl+o); ctrl+r is only
    // bound inside the session tree overlay.
    const text = panelLines(80).join("\n");
    expect(text).not.toContain("ctrl-r");
    expect(text).toContain("ctrl-o");
  });

  it("never emits a line wider than the given width (issue #48 safety)", () => {
    for (const width of [20, 30, 40, 80, 120]) {
      for (const line of panelLines(width)) {
        expect(visibleWidth(line)).toBeLessThanOrEqual(width);
      }
    }
  });

  it("aligns descriptions into a column (keys padded to equal width)", () => {
    // Descriptions should start at the same visible offset whether the key is a
    // single char (`/`) or the longest (`shift-tab`), since keys are padded.
    const strip = (l: string) => l.replace(/\x1b\[[0-9;]*m/g, "");
    const lines = panelLines(120).map(strip);
    const esc = lines.find((l) => l.includes("interrupt"))!;
    const plan = lines.find((l) => l.includes("toggle plan mode"))!;
    expect(esc.indexOf("interrupt")).toBe(plan.indexOf("toggle plan mode"));
  });
});
