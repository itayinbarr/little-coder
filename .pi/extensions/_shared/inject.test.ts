import { describe, expect, it } from "vitest";
import { injectMode, injectionResult, makeDedupe } from "./inject.ts";

const messageMode = {} as NodeJS.ProcessEnv;
const systemMode = { LITTLE_CODER_INJECT_MODE: "system" } as NodeJS.ProcessEnv;

describe("injectMode", () => {
  it("defaults to tail-message delivery", () => {
    expect(injectMode(messageMode)).toBe("message");
    expect(injectMode({ LITTLE_CODER_INJECT_MODE: "" } as NodeJS.ProcessEnv)).toBe("message");
    // Anything other than the exact opt-out keeps the cache-safe default.
    expect(injectMode({ LITTLE_CODER_INJECT_MODE: "msg" } as NodeJS.ProcessEnv)).toBe("message");
  });

  it("honors the LITTLE_CODER_INJECT_MODE=system escape hatch", () => {
    expect(injectMode(systemMode)).toBe("system");
  });
});

describe("injectionResult", () => {
  it("returns a hidden tail message and never touches the system prompt", () => {
    const result = injectionResult("lc-skills", "GUIDANCE", "SYSTEM", messageMode);
    expect(result).toEqual({
      message: { customType: "lc-skills", content: "GUIDANCE", display: false },
    });
    // This is the whole point of #73: the cached prefix must be left alone.
    expect(result?.systemPrompt).toBeUndefined();
  });

  it("appends to the system prompt in system mode", () => {
    expect(injectionResult("lc-skills", "GUIDANCE", "SYSTEM", systemMode)).toEqual({
      systemPrompt: "SYSTEMGUIDANCE",
    });
  });

  it("returns undefined for an empty block in either mode", () => {
    expect(injectionResult("lc-skills", "", "SYSTEM", messageMode)).toBeUndefined();
    expect(injectionResult("lc-skills", "", "SYSTEM", systemMode)).toBeUndefined();
  });
});

describe("makeDedupe", () => {
  it("suppresses a block identical to the previous one", () => {
    const should = makeDedupe(messageMode);
    expect(should("A")).toBe(true);
    expect(should("A")).toBe(false); // still in the conversation from last turn
    expect(should("B")).toBe(true);
    expect(should("B")).toBe(false);
    expect(should("A")).toBe(true); // changed away and back — must be re-sent
  });

  it("never suppresses in system mode, where the prompt is rebuilt each turn", () => {
    const should = makeDedupe(systemMode);
    expect(should("A")).toBe(true);
    expect(should("A")).toBe(true);
  });

  it("keeps separate state per injector", () => {
    const skills = makeDedupe(messageMode);
    const knowledge = makeDedupe(messageMode);
    expect(skills("A")).toBe(true);
    expect(knowledge("A")).toBe(true); // not shadowed by skill-inject's state
  });
});
