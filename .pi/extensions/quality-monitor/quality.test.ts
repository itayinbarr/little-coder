import { describe, it, expect, beforeEach } from "vitest";
import { assessResponse, buildCorrectionMessage, phraseForUser } from "./quality.ts";
import setupQualityMonitor from "./index.ts";

const known = new Set(["Read", "Write", "Edit", "Bash", "Glob", "Grep"]);

describe("assessResponse", () => {
  it("accepts text-only assistant response", () => {
    expect(assessResponse("here's my thinking", [], [], known)).toEqual({ ok: true });
  });
  it("accepts valid tool calls", () => {
    const calls = [{ name: "Read", input: { file_path: "/a" } }];
    expect(assessResponse("", calls, [], known)).toEqual({ ok: true });
  });
  it("detects empty response (no text, no calls)", () => {
    expect(assessResponse("", [], [], known)).toEqual({
      ok: false, reason: "empty_response",
    });
  });
  it("detects empty tool name", () => {
    expect(assessResponse("", [{ name: "", input: {} }], [], known)).toEqual({
      ok: false, reason: "empty_tool_name",
    });
  });
  it("detects hallucinated tool name", () => {
    const result = assessResponse("", [{ name: "FakeTool", input: {} }], [], known);
    expect(result).toEqual({ ok: false, reason: "unknown_tool:FakeTool" });
  });
  it("skips hallucination check when registry empty", () => {
    expect(
      assessResponse("", [{ name: "Anything", input: {} }], [], new Set()),
    ).toEqual({ ok: true });
  });
  it("detects repeated tool call", () => {
    const now = [{ name: "Read", input: { file_path: "/a" } }];
    const prev = [{ name: "Read", input: { file_path: "/a" } }];
    expect(assessResponse("", now, prev, known)).toEqual({
      ok: false, reason: "repeated_tool_call",
    });
  });
  it("does not flag as repeat when inputs differ", () => {
    const now = [{ name: "Read", input: { file_path: "/a" } }];
    const prev = [{ name: "Read", input: { file_path: "/b" } }];
    expect(assessResponse("", now, prev, known)).toEqual({ ok: true });
  });
  it("does not flag a re-run build command when the prior turn also edited a file (#81)", () => {
    const build = { name: "Bash", input: { command: "npm run build" } };
    const now = [build];
    // Prior turn: fixed a source file AND ran the build — re-running the build
    // now is progress, not a loop, because the Edit changed the environment.
    const prev = [{ name: "Edit", input: { file_path: "/src/main.ts" } }, build];
    expect(assessResponse("", now, prev, known)).toEqual({ ok: true });
  });
  it("still flags a verbatim repeat when nothing else changed", () => {
    const build = { name: "Bash", input: { command: "npm run build" } };
    expect(assessResponse("", [build], [build], known)).toEqual({
      ok: false, reason: "repeated_tool_call",
    });
  });
  it("still flags a repeat when the only other calls are read-only (#81)", () => {
    const build = { name: "Bash", input: { command: "npm run build" } };
    const now = [build];
    const prev = [{ name: "Read", input: { file_path: "/log" } }, build];
    expect(assessResponse("", now, prev, known)).toEqual({
      ok: false, reason: "repeated_tool_call",
    });
  });
  it("detects malformed args sentinel", () => {
    const calls = [{ name: "Read", input: { _raw: "garbage" } }];
    expect(assessResponse("", calls, [], known)).toEqual({
      ok: false, reason: "malformed_args:Read",
    });
  });
});

describe("buildCorrectionMessage", () => {
  it("generates empty-response message", () => {
    const m = buildCorrectionMessage("empty_response");
    expect(m).toContain("empty");
  });
  it("generates unknown-tool message with tool name", () => {
    const m = buildCorrectionMessage("unknown_tool:FakeTool");
    expect(m).toContain("'FakeTool'");
    expect(m).toContain("does not exist");
  });
  it("generates malformed-args message", () => {
    const m = buildCorrectionMessage("malformed_args:Read");
    expect(m).toContain("'Read'");
    expect(m).toContain("malformed");
  });
  it("generates repeated-tool-call message", () => {
    const m = buildCorrectionMessage("repeated_tool_call");
    expect(m).toContain("loop");
  });
  it("falls back to generic on unknown reason", () => {
    expect(buildCorrectionMessage("weird_thing")).toContain("weird_thing");
  });
});

describe("phraseForUser", () => {
  it("phrases known reasons in plain language", () => {
    expect(phraseForUser("empty_response")).toMatch(/empty response/i);
    expect(phraseForUser("repeated_tool_call")).toMatch(/repeated/i);
  });
  it("includes the tool name for parameterized reasons", () => {
    expect(phraseForUser("unknown_tool:Frobnicate")).toContain("Frobnicate");
    expect(phraseForUser("malformed_args:Edit")).toContain("Edit");
  });
});

// ── turn_end handler: must skip interrupted/aborted turns ───────────────────
function harness() {
  const handlers: Record<string, ((e: any, c: any) => any)[]> = {};
  const followUps: { msg: string; opts: any }[] = [];
  const pi = {
    handlers,
    on(name: string, h: (e: any, c: any) => any) {
      (handlers[name] ??= []).push(h);
    },
    sendUserMessage(msg: string, opts: any) {
      followUps.push({ msg, opts });
    },
  };
  const notifies: string[] = [];
  const ctx = { ui: { notify: (m: string) => notifies.push(m) } };
  setupQualityMonitor(pi as any);
  return { pi, ctx, followUps, notifies };
}
async function fire(h: any, name: string, event: any) {
  for (const fn of h.pi.handlers[name] ?? []) await fn(event, h.ctx);
}

describe("quality-monitor turn_end", () => {
  let h: ReturnType<typeof harness>;
  beforeEach(async () => {
    h = harness();
    await fire(h, "session_start", {}); // reset session-scoped counters
  });

  it("skips an aborted/interrupted turn — no empty_response correction", async () => {
    // An ESC interrupt or harness abort produces a partial/empty message with
    // stopReason "aborted". This is the escape-interrupt bug: it must NOT steer
    // a 'your previous response was empty' correction onto the next prompt.
    await fire(h, "turn_end", { message: { stopReason: "aborted", content: [] } });
    expect(h.followUps).toHaveLength(0);
    expect(h.notifies).toHaveLength(0);
  });

  it("flags a genuinely empty COMPLETED turn and steers a correction", async () => {
    await fire(h, "turn_end", { message: { stopReason: "stop", content: [] } });
    expect(h.followUps).toHaveLength(1);
    expect(h.followUps[0].opts).toEqual({ deliverAs: "steer" });
    expect(h.notifies[0]).toMatch(/harness intervention:/i);
  });

  it("passes a normal text turn without intervention", async () => {
    await fire(h, "turn_end", {
      message: { stopReason: "stop", content: [{ type: "text", text: "done." }] },
    });
    expect(h.followUps).toHaveLength(0);
    expect(h.notifies).toHaveLength(0);
  });

  it("does not steer an empty-response correction on a provider error turn (#86)", async () => {
    // A 400 from the backend arrives as stopReason "error" with empty content.
    // It must NOT be treated as an empty model response and re-sent.
    await fire(h, "turn_end", {
      message: {
        stopReason: "error",
        errorMessage: '400 "gemma-4-26B" does not support thinking',
        content: [],
      },
    });
    expect(h.followUps).toHaveLength(0);
  });

  it("adds a one-time hint when the error is a thinking rejection (#86)", async () => {
    await fire(h, "turn_end", {
      message: {
        stopReason: "error",
        errorMessage: '400 "gemma-4-26B" does not support thinking',
        content: [],
      },
    });
    // No correction is steered, but a user-facing hint about the thinking level fires.
    expect(h.followUps).toHaveLength(0);
    expect(h.notifies.join("\n")).toMatch(/thinking level/i);
  });

  it("stays silent on an unrelated provider error (#86)", async () => {
    await fire(h, "turn_end", {
      message: { stopReason: "error", errorMessage: "500 upstream timeout", content: [] },
    });
    expect(h.followUps).toHaveLength(0);
    expect(h.notifies).toHaveLength(0);
  });
});
