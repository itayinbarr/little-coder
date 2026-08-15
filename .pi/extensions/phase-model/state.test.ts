import { describe, it, expect, vi } from "vitest";

// pi loads every bundled extension with its own `--extension <path>`, and
// plan-mode ALSO imports phase-model to call enterPhase(). Those two paths are
// not guaranteed to resolve to the same module instance, so holding the phase
// tags in a module-level binding gives the commands one copy and plan-mode
// another, empty one.
//
// The failure is silent and looks like the feature working: `/plan-model` sets
// the tag, the footer indicator updates from it, and then Plan Mode runs on the
// active model anyway with no error to explain why. It was caught only by
// watching the real TUI's status line fail to change while the footer claimed
// otherwise.
//
// So the tags live on globalThis. This test reproduces the two-instance case
// directly: load the module twice with the registry reset in between (which is
// exactly what a second `--extension` load looks like) and require that a tag
// set through the first is visible through the second.

const STATE_KEY = "__littleCoderPhaseModel";
const ctxOn = (ref: string) => ({ model: { provider: ref.split("/")[0], id: ref.split("/")[1] } });

describe("phase-model state survives being loaded twice", () => {
  it("a tag set in one module instance is read by another", async () => {
    delete (globalThis as any)[STATE_KEY];

    // Instance A — what the `/plan-model` command handler runs in.
    vi.resetModules();
    const a = await import("./index.ts");
    a.resetState();
    (globalThis as any)[STATE_KEY].planModel = "llamacpp/planner";

    // Instance B — what plan-mode's `import { enterPhase }` would resolve to.
    vi.resetModules();
    const b = await import("./index.ts");

    // The bug: B answered with the active model because its own copy was empty.
    expect(b.phaseModel(ctxOn("llamacpp/active"), "plan")).toBe("llamacpp/planner");
    expect(b.phaseModel(ctxOn("llamacpp/active"), "action")).toBe("llamacpp/active");
  });

  it("keeps the tags on globalThis, not in a module binding", async () => {
    delete (globalThis as any)[STATE_KEY];
    vi.resetModules();
    const mod = await import("./index.ts");
    mod.resetState();

    const shared = (globalThis as any)[STATE_KEY];
    expect(shared, "phase state must be reachable off globalThis").toBeDefined();
    expect(shared).toHaveProperty("handover");
  });
});
