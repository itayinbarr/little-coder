import { describe, it, expect, afterEach } from "vitest";
import { allowedToolSet, toolsAvailable } from "./allowed-tools.ts";

const ENV = "LITTLE_CODER_ALLOWED_TOOLS";

afterEach(() => {
  delete process.env[ENV];
});

describe("allowedToolSet", () => {
  it("is undefined when nothing is gated", () => {
    expect(allowedToolSet({})).toBeUndefined();
    expect(allowedToolSet(undefined)).toBeUndefined();
  });

  it("prefers the list published on systemPromptOptions", () => {
    process.env[ENV] = "read";
    const set = allowedToolSet({ allowedTools: ["read", "grep"] });
    expect(set).toEqual(new Set(["read", "grep"]));
  });

  it("falls back to the env var when tool-gating has not published yet", () => {
    process.env[ENV] = "read, grep ,glob";
    expect(allowedToolSet({})).toEqual(new Set(["read", "grep", "glob"]));
  });

  it("treats an empty list as ungated", () => {
    process.env[ENV] = "";
    expect(allowedToolSet({ allowedTools: [] })).toBeUndefined();
  });
});

describe("toolsAvailable", () => {
  it("is true for everything when nothing is gated", () => {
    expect(toolsAvailable(["EvidenceAdd"], undefined)).toBe(true);
  });

  it("requires every named tool to be present", () => {
    const allowed = new Set(["read", "BrowserExtract"]);
    expect(toolsAvailable(["read"], allowed)).toBe(true);
    expect(toolsAvailable(["read", "BrowserExtract"], allowed)).toBe(true);
    expect(toolsAvailable(["read", "EvidenceAdd"], allowed)).toBe(false);
  });

  it("is true for an empty requirement list", () => {
    expect(toolsAvailable([], new Set(["read"]))).toBe(true);
  });

  it("matches the real sub-coder allow-list against the research protocol", async () => {
    const { SUBCODER_ALLOWED_TOOLS } = await import("../subagent/spawn.ts");
    const allowed = new Set(SUBCODER_ALLOWED_TOOLS.split(","));
    // Issue #97: this is exactly why the protocol must not reach a sub-coder.
    expect(toolsAvailable(["EvidenceAdd", "EvidenceList"], allowed)).toBe(false);
    expect(toolsAvailable(["BrowserNavigate", "BrowserExtract"], allowed)).toBe(true);
  });
});
