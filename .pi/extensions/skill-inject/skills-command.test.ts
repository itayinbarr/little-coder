import { describe, it, expect } from "vitest";
import { applySkillsCommand, skillInventory } from "./index.ts";

// #118: pi's /skill:name addresses pi skills. little-coder's tool skill cards
// are a separate mechanism, so there was no way to see what was loaded or to
// override the selector when two cards competed for the same turn.
describe("/skills (issue #118)", () => {
  it("lists the loaded cards", () => {
    const rows = skillInventory();
    expect(rows.length).toBeGreaterThan(0);
    expect(rows.map((r) => r.tool)).toContain("bash");
    // sorted and stable
    expect([...rows].sort((a, b) => a.tool.localeCompare(b.tool))).toEqual(rows);
  });

  it("with no argument, reports the inventory", () => {
    const out = applySkillsCommand("");
    expect(out).toMatch(/tool skill cards loaded/);
    expect(out).toContain("bash");
  });

  it("pins a card by name and reports it as pinned", () => {
    expect(applySkillsCommand("bash")).toMatch(/pinned the bash skill card/);
    expect(skillInventory().find((r) => r.tool === "bash")?.pinned).toBe(true);
  });

  it("clears the pin", () => {
    applySkillsCommand("bash");
    expect(applySkillsCommand("off")).toMatch(/pin cleared/);
    expect(skillInventory().some((r) => r.pinned)).toBe(false);
  });

  it("names the loaded cards when asked for one that does not exist", () => {
    const out = applySkillsCommand("definitely-not-a-tool");
    expect(out).toMatch(/no skill card for "definitely-not-a-tool"/);
    expect(out).toContain("bash");
  });
});
