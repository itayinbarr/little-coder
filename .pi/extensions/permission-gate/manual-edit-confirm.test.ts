import { describe, it, expect } from "vitest";
import { createEditConfirmer } from "./manual-edit-confirm.ts";

describe("createEditConfirmer", () => {
  it("denies when no select UI is available (headless)", async () => {
    const c = createEditConfirmer();
    expect(await c.confirm({ ui: {} }, "write", { path: "/x" })).toBe("deny");
  });

  it("resolves Apply", async () => {
    const c = createEditConfirmer();
    const decision = await c.confirm(
      {
        cwd: "/cwd",
        ui: { select: async () => "Apply" },
      },
      "edit",
      { path: "/x.ts", edits: [{ oldText: "a", newText: "b" }] },
    );
    expect(decision).toBe("apply");
  });

  it("auto-approves after Apply all without prompting again", async () => {
    const c = createEditConfirmer();
    const first = await c.confirm(
      { cwd: "/cwd", ui: { select: async () => "Apply all (this session)" } },
      "write",
      { path: "/x.ts", content: "y" },
    );
    expect(first).toBe("apply-all");
    let prompted = false;
    const second = await c.confirm(
      { cwd: "/cwd", ui: { select: async () => { prompted = true; return "Deny"; } } },
      "write",
      { path: "/x.ts", content: "y" },
    );
    expect(second).toBe("apply");
    expect(prompted).toBe(false);
  });

  it("keeps two instances isolated", async () => {
    const a = createEditConfirmer();
    const b = createEditConfirmer();
    await a.confirm({ cwd: "/cwd", ui: { select: async () => "Apply all (this session)" } }, "write", { path: "/x", content: "y" });
    let bPrompted = false;
    await a.confirm({ cwd: "/cwd", ui: { select: async () => { bPrompted = true; return "Deny"; } } }, "write", { path: "/x", content: "y" });
    expect(bPrompted).toBe(false);
    let b2Prompted = false;
    const bDecision = await b.confirm({ cwd: "/cwd", ui: { select: async () => { b2Prompted = true; return "Deny"; } } }, "write", { path: "/x", content: "y" });
    expect(b2Prompted).toBe(true);
    expect(bDecision).toBe("deny");
  });
});
