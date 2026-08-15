import { describe, it, expect, afterEach, vi } from "vitest";
import {
  extractJsonArray,
  digestReports,
  wantsPlanModeAtStart,
  extractPlanText,
  handlePlanApproval,
  handleImplement,
} from "./index.ts";
import type { SubCoderResult } from "../subagent/spawn.ts";

export {
  extractJsonArray,
  digestReports,
  wantsPlanModeAtStart,
  extractPlanText,
  handlePlanApproval,
  handleImplement,
};

describe("wantsPlanModeAtStart (issue #84)", () => {
  const origEnv = process.env.LITTLE_CODER_PLAN_MODE;
  const origSub = process.env.LITTLE_CODER_SUBAGENT;
  const origArgv = process.argv;
  afterEach(() => {
    if (origEnv === undefined) delete process.env.LITTLE_CODER_PLAN_MODE;
    else process.env.LITTLE_CODER_PLAN_MODE = origEnv;
    if (origSub === undefined) delete process.env.LITTLE_CODER_SUBAGENT;
    else process.env.LITTLE_CODER_SUBAGENT = origSub;
    process.argv = origArgv;
  });

  it("is off when the env flag is unset", () => {
    delete process.env.LITTLE_CODER_PLAN_MODE;
    delete process.env.LITTLE_CODER_SUBAGENT;
    process.argv = ["node", "pi"];
    expect(wantsPlanModeAtStart()).toBe(false);
  });
  it("is on for an interactive session with the flag set", () => {
    process.env.LITTLE_CODER_PLAN_MODE = "1";
    delete process.env.LITTLE_CODER_SUBAGENT;
    process.argv = ["node", "pi"];
    expect(wantsPlanModeAtStart()).toBe(true);
  });
  it("stays off for a headless run even with the flag set", () => {
    process.env.LITTLE_CODER_PLAN_MODE = "1";
    delete process.env.LITTLE_CODER_SUBAGENT;
    process.argv = ["node", "pi", "--mode", "json", "-p"];
    expect(wantsPlanModeAtStart()).toBe(false);
  });
  it("stays off in a sub-coder that inherited the env flag", () => {
    process.env.LITTLE_CODER_PLAN_MODE = "1";
    process.env.LITTLE_CODER_SUBAGENT = "1";
    process.argv = ["node", "pi"];
    expect(wantsPlanModeAtStart()).toBe(false);
  });
});

describe("extractJsonArray", () => {
  it("parses a bare JSON array", () => {
    expect(extractJsonArray('[{"label":"a","task":"t"}]')).toEqual([
      { label: "a", task: "t" },
    ]);
  });
  it("pulls the array out of surrounding prose / fences", () => {
    const text =
      'Here is the plan:\n```json\n[{"q":"why?","options":["a","b"]}]\n```\nThanks!';
    expect(extractJsonArray(text)).toEqual([
      { q: "why?", options: ["a", "b"] },
    ]);
  });
  it("returns [] when there is no array", () => {
    expect(extractJsonArray("no json here")).toEqual([]);
    expect(extractJsonArray("")).toEqual([]);
  });
  it("returns [] on malformed JSON rather than throwing", () => {
    expect(extractJsonArray("[ this is not, valid json ]")).toEqual([]);
  });
});

describe("digestReports", () => {
  const mk = (over: Partial<SubCoderResult>): SubCoderResult => ({
    id: "1",
    label: "x",
    task: "t",
    exitCode: 0,
    report: "",
    messages: [],
    stderr: "",
    usage: {
      input: 0,
      output: 0,
      cost: 0,
      turns: 0,
      contextTokens: 0,
    },
    ...over,
  });

  it("renders each report under its label heading", () => {
    const out = digestReports([
      mk({ label: "auth", report: "uses JWT" }),
      mk({ label: "db", report: "postgres" }),
    ]);
    expect(out).toContain("### auth\nuses JWT");
    expect(out).toContain("### db\npostgres");
  });

  it("marks failed sub-coders instead of dropping them", () => {
    const out = digestReports([
      mk({ label: "web", exitCode: 1, errorMessage: "timeout" }),
    ]);
    expect(out).toContain("### web");
    expect(out).toContain("failed: timeout");
  });
});


describe("issue #98 - extractPlanText", () => {
  it("extracts plan from a simple single-part assistant message", () => {
    const messages = [
      { role: "user", content: [{ type: "text", text: "Fix the bug" }] },
      {
        role: "assistant",
        content: [
          {
            type: "text",
            text: "Here is the plan:\n\n1. Read auth.py\n2. Fix the login flow",
          },
        ],
      },
    ];
    expect(extractPlanText(messages)).toBe(
      "Here is the plan:\n\n1. Read auth.py\n2. Fix the login flow",
    );
  });

  it("multiple text parts preserve their boundaries/order", () => {
    const messages = [
      { role: "user", content: [{ type: "text", text: "Hello" }] },
      {
        role: "assistant",
        content: [
          { type: "text", text: "Part one: " },
          {
            type: "toolCall",
            name: "read",
            arguments: { path: "config.py" },
          },
          { type: "text", text: "Part two: " },
          { type: "text", text: "final plan" },
        ],
      },
    ];
    expect(extractPlanText(messages)).toBe(
      "Part one: \nPart two: \nfinal plan",
    );
  });

  it("no assistant message -> empty", () => {
    const messages = [
      { role: "user", content: [{ type: "text", text: "Hello" }] },
      { role: "tool", content: [{ type: "text", text: "config loaded" }] },
    ];
    expect(extractPlanText(messages)).toBe("");
  });

  it("latest assistant has no text -> empty", () => {
    const messages = [
      { role: "user", content: [{ type: "text", text: "Hello" }] },
      {
        role: "assistant",
        content: [
          { type: "toolCall", name: "read", arguments: { path: "x" } },
        ],
      },
    ];
    expect(extractPlanText(messages)).toBe("");
  });

  it("latest assistant has no text does NOT fall back to an older assistant", () => {
    const messages = [
      { role: "user", content: [{ type: "text", text: "Hello" }] },
      {
        role: "assistant",
        content: [{ type: "text", text: "Old plan text" }],
      },
      { role: "user", content: [{ type: "text", text: "Again" }] },
      {
        role: "assistant",
        content: [
          { type: "toolCall", name: "read", arguments: { path: "x" } },
        ],
      },
    ];
    expect(extractPlanText(messages)).toBe("");
  });

  it("whitespace handling", () => {
    const messages = [
      { role: "user", content: [{ type: "text", text: "Hello" }] },
      {
        role: "assistant",
        content: [
          { type: "text", text: "" },
          { type: "text", text: "   " },
          { type: "text", text: "  actual plan  " },
        ],
      },
    ];
    expect(extractPlanText(messages)).toBe("actual plan");
  });

  it("handles undefined / null messages gracefully", () => {
    expect(extractPlanText([])).toBe("");
    expect(extractPlanText([undefined as any])).toBe("");
    expect(extractPlanText([null as any])).toBe("");
  });

  it("handles messages with missing content array", () => {
    const messages = [{ role: "assistant" }];
    expect(extractPlanText(messages)).toBe("");
  });
});


describe("issue #98 - handlePlanApproval", () => {
  const PLAN_FILE = ".pi/approved-plan.md";

  interface MockFs {
    writeFileSyncCalls: { path: string; content: string }[];
    mkdirSyncCalls: { path: string; opts: { recursive: boolean } }[];
    planContent: string;
    writeFileSyncFail?: boolean;
    writeFileSync: (path: string, content: string, options?: any) => void;
    mkdirSync: (path: string, opts: { recursive: boolean }) => void;
    readFileSync: (path: string, options?: any) => string;
  }

  function buildDeps(
    planText: string,
    approved: boolean,
  ): {
    deps: {
      planText: string;
      approved: boolean;
      planFile: string;
      fs: MockFs;
      ui: { notifyCalls: { msg: string; type?: string }[]; notify: (msg: string, type?: string) => void };
    };
    fs: MockFs;
    ui: { notifyCalls: { msg: string; type?: string }[]; notify: (msg: string, type?: string) => void };
  } {
    const fs: MockFs = {
      writeFileSyncCalls: [],
      mkdirSyncCalls: [],
      planContent: "",
      writeFileSyncFail: false,
      writeFileSync: (path: string, content: string) => {
        fs.writeFileSyncCalls.push({ path, content });
        if (path === PLAN_FILE) {
          fs.planContent = content;
        }
        if (fs.writeFileSyncFail) {
          throw new Error("simulated write failure");
        }
      },
      mkdirSync: (path: string, opts: { recursive: boolean }) => {
        fs.mkdirSyncCalls.push({ path, opts });
      },
      readFileSync: (path: string, options?: any) => {
        return "";
      },
    };

    const ui = {
      notifyCalls: [] as { msg: string; type?: string }[],
      notify: (msg: string, type?: string) => {
        ui.notifyCalls.push({ msg, type });
      },
    };

    const deps = {
      planText,
      approved,
      planFile: PLAN_FILE,
      fs,
      ui,
    };

    return { deps, fs, ui };
  }

  it("approval persists the exact plan", () => {
    const planText = "Step 1: Read auth.py\nStep 2: Fix login flow";
    const { deps, fs } = buildDeps(planText, true);

    const result = handlePlanApproval(deps);

    expect(result).toBe(true);
    expect(fs.writeFileSyncCalls.length).toBe(1);
    expect(fs.writeFileSyncCalls[0].content).toBe(planText);
  });

  it("parent directory is created recursively", () => {
    const { deps, fs } = buildDeps("Step 1: Read config", true);

    handlePlanApproval(deps);

    expect(fs.mkdirSyncCalls).toHaveLength(1);
    expect(fs.mkdirSyncCalls[0].path).toBe(".pi");
    expect(fs.mkdirSyncCalls[0].opts).toEqual({ recursive: true });
  });

  it("empty/whitespace plan is rejected", () => {
    const { deps, ui } = buildDeps("", true);

    const result = handlePlanApproval(deps);

    expect(result).toBe(false);
    expect(ui.notifyCalls.length).toBe(1);
    expect(ui.notifyCalls[0].type).toBe("warning");
    expect(ui.notifyCalls[0].msg).toContain("could not be captured");
  });

  it("persistence failure is reported", () => {
    const { deps, fs, ui } = buildDeps("Step 1: Read config", true);
    fs.writeFileSyncFail = true;

    const result = handlePlanApproval(deps);

    expect(result).toBe(false);
    expect(ui.notifyCalls.length).toBe(1);
    expect(ui.notifyCalls[0].type).toBe("warning");
    expect(ui.notifyCalls[0].msg).toContain("failed to save plan");
  });

  it("non-approval performs no persistence", () => {
    const { deps, fs, ui } = buildDeps("Plan: fix auth", false);

    const result = handlePlanApproval(deps);

    expect(result).toBe(false);
    expect(fs.writeFileSyncCalls.length).toBe(0);
    expect(fs.mkdirSyncCalls.length).toBe(0);
    expect(ui.notifyCalls.length).toBe(1);
    expect(ui.notifyCalls[0].msg).toContain("not approved");
  });

  it("approval notifies with the saved plan path", () => {
    const { deps, ui } = buildDeps("Plan: fix auth", true);

    handlePlanApproval(deps);

    expect(ui.notifyCalls.length).toBe(1);
    expect(ui.notifyCalls[0].type).toBe("info");
    expect(ui.notifyCalls[0].msg).toContain("plan saved to");
    expect(ui.notifyCalls[0].msg).toContain(PLAN_FILE);
    expect(ui.notifyCalls[0].msg).toContain("/implement");
  });

  it("approval with whitespace-only plan is rejected", () => {
    const { deps, ui } = buildDeps("   \n\n  ", true);

    const result = handlePlanApproval(deps);

    expect(result).toBe(false);
    expect(ui.notifyCalls.length).toBe(1);
    expect(ui.notifyCalls[0].type).toBe("warning");
    expect(ui.notifyCalls[0].msg).toContain("could not be captured");
  });
});


describe("issue #98 - handleImplement", () => {
  const PLAN_FILE = ".pi/approved-plan.md";

  interface MockFs {
    planContent: string;
    readFileSyncFail?: boolean;
    readFileSync: (path: string, options?: any) => string;
    writeFileSync: (path: string, content: string, options?: any) => void;
    mkdirSync: (path: string, opts: { recursive: boolean }) => void;
  }

  interface BuildResult {
    deps: {
      cwd: string;
      planFile: string;
      ui: { notifyCalls: { msg: string; type?: string }[]; notify: (msg: string, type?: string) => void };
      fs: MockFs;
      pi: any;
      ctx: any;
      enterPhase: (...args: any[]) => Promise<string | undefined>;
      newSession: (
        opts?: {
          setup?: (sm: any) => Promise<void>;
          withSession?: (ctx: any) => Promise<void>;
        },
      ) => Promise<{ cancelled: boolean }>;
    };
    fs: MockFs;
    ui: { notifyCalls: { msg: string; type?: string }[]; notify: (msg: string, type?: string) => void };
    newSession: {
      called: boolean;
      opts: any;
      setupCallback: ((sm: any) => Promise<void>) | undefined;
      withSessionCallback: ((ctx: any) => Promise<void>) | undefined;
      cancelled: boolean;
      shouldThrow: boolean;
      throwMessage: string;
    };
    enterPhaseCalls: { pi: any; ctx: any; phase: string }[];
  }

  function buildDeps(planContent: string): BuildResult {
    const enterPhaseCalls: {
      pi: any;
      ctx: any;
      phase: string;
    }[] = [];

    const fs: MockFs = {
      planContent,
      readFileSyncFail: false,
      readFileSync: (path: string, options?: any) => {
        if (fs.readFileSyncFail) {
          throw new Error("simulated read failure");
        }
        return fs.planContent;
      },
      writeFileSync: () => {},
      mkdirSync: () => {},
    };

    const ui = {
      notifyCalls: [] as { msg: string; type?: string }[],
      notify: (msg: string, type?: string) => {
        ui.notifyCalls.push({ msg, type });
      },
    };

    const newSessionState = {
      called: false,
      opts: null as any,
      setupCallback: undefined as
        | ((sm: any) => Promise<void>)
        | undefined,
      withSessionCallback: undefined as
        | ((ctx: any) => Promise<void>)
        | undefined,
      cancelled: false,
      shouldThrow: false,
      throwMessage: "",
    };

    const deps = {
      cwd: "/workspace",
      planFile: PLAN_FILE,
      ui,
      fs,
      pi: {},
      ctx: {},
      enterPhase: async (pi: any, ctx: any, phase: string) => {
        enterPhaseCalls.push({ pi, ctx, phase });
        return undefined;
      },
      newSession: async (
        opts?: {
          setup?: (sm: any) => Promise<void>;
          withSession?: (ctx: any) => Promise<void>;
        },
      ) => {
        newSessionState.called = true;
        newSessionState.opts = opts;
        if (opts?.setup) {
          newSessionState.setupCallback = opts.setup;
        }
        if (opts?.withSession) {
          newSessionState.withSessionCallback = opts.withSession;
        }
        if (newSessionState.shouldThrow) {
          throw new Error(newSessionState.throwMessage);
        }
        return { cancelled: newSessionState.cancelled };
      },
    };

    return { deps, fs, ui, newSession: newSessionState, enterPhaseCalls };
  }

  it("reads the saved plan and calls newSession", async () => {
    const planText = "Step 1: Read auth.py\nStep 2: Fix login flow";
    const { deps, newSession } = buildDeps(planText);

    await handleImplement(deps);

    expect(newSession.called).toBe(true);
    expect(newSession.setupCallback).toBeDefined();
    expect(newSession.withSessionCallback).toBeDefined();
  });

  it("enters the action phase before newSession", async () => {
    const planText = "Step 1: Read auth.py";
    const { deps, enterPhaseCalls } = buildDeps(planText);

    await handleImplement(deps);

    expect(enterPhaseCalls.length).toBe(1);
    expect(enterPhaseCalls[0].phase).toBe("action");
  });

  it("seeds the SessionManager with the plan via setup", async () => {
    const planText = "Step 1: Read auth.py\nStep 2: Fix login flow";
    const { deps, newSession } = buildDeps(planText);

    // First call handleImplement to populate the callbacks
    await handleImplement(deps);

    // Now invoke the setup callback with a mock SessionManager
    let callArgs: {
      key: string;
      content: string;
      hidden: boolean;
      meta: { source: string };
    } | null = null;
    const mockSm = {
      appendCustomMessageEntry: (
        key: string,
        content: string,
        hidden: boolean,
        meta: { source: string },
      ) => {
        callArgs = { key, content, hidden, meta };
      },
    };

    await newSession.setupCallback!(mockSm);

    expect(callArgs).not.toBeNull();
    expect(callArgs!.key).toBe("lc-approved-plan");
    expect(callArgs!.content).toContain("## Approved implementation plan");
    expect(callArgs!.content).toContain(planText);
    expect(callArgs!.hidden).toBe(false);
    expect(callArgs!.meta.source).toBe(PLAN_FILE);
  });

  it("sends the implementation instruction via withSession", async () => {
    const planText = "Step 1: Read auth.py\nStep 2: Fix login flow";
    const { deps, newSession } = buildDeps(planText);

    // First call handleImplement to populate the callbacks
    await handleImplement(deps);

    // Now invoke the withSession callback with a mock context
    let sentMessage = "";
    const mockNewCtx = {
      sendUserMessage: async (msg: string) => {
        sentMessage = msg;
      },
    };

    await newSession.withSessionCallback!(mockNewCtx);

    expect(sentMessage).toBe(
      "Implement the approved plan provided in this session context. Make the actual file changes now.",
    );
  });

  it("handles cancelled result", async () => {
    const planText = "Step 1: Read auth.py";
    const { deps, ui, newSession } = buildDeps(planText);
    newSession.cancelled = true;

    await handleImplement(deps);

    expect(ui.notifyCalls.length).toBe(1);
    expect(ui.notifyCalls[0].type).toBe("info");
    expect(ui.notifyCalls[0].msg).toContain("cancelled");
    expect(ui.notifyCalls[0].msg).toContain("approved plan remains");
  });

  it("handles newSession failure with notify", async () => {
    const planText = "Step 1: Read auth.py";
    const { deps, ui, newSession } = buildDeps(planText);
    newSession.shouldThrow = true;
    newSession.throwMessage = "session failed";

    await handleImplement(deps);

    expect(ui.notifyCalls.length).toBe(1);
    expect(ui.notifyCalls[0].type).toBe("error");
    expect(ui.notifyCalls[0].msg).toContain("session replacement failed");
    expect(ui.notifyCalls[0].msg).toContain("session failed");
  });

  it("handles missing plan file", async () => {
    const { deps, ui, fs, enterPhaseCalls, newSession } = buildDeps("");
    fs.readFileSyncFail = true;

    await handleImplement(deps);

    expect(ui.notifyCalls.length).toBe(1);
    expect(ui.notifyCalls[0].type).toBe("warning");
    expect(ui.notifyCalls[0].msg).toContain("could not read approved plan");
    expect(enterPhaseCalls.length).toBe(0);
    expect(newSession.called).toBe(false);
  });

  it("handles empty plan file", async () => {
    const { deps, ui, enterPhaseCalls, newSession } = buildDeps("");

    await handleImplement(deps);

    expect(ui.notifyCalls.length).toBe(1);
    expect(ui.notifyCalls[0].type).toBe("warning");
    expect(ui.notifyCalls[0].msg).toContain("is empty");
    expect(enterPhaseCalls.length).toBe(0);
    expect(newSession.called).toBe(false);
  });

  it("handles whitespace-only plan file", async () => {
    const { deps, ui, enterPhaseCalls, newSession } = buildDeps("   \n\n  ");

    await handleImplement(deps);

    expect(ui.notifyCalls.length).toBe(1);
    expect(ui.notifyCalls[0].type).toBe("warning");
    expect(ui.notifyCalls[0].msg).toContain("is empty");
    expect(enterPhaseCalls.length).toBe(0);
    expect(newSession.called).toBe(false);
  });

  it("does not modify the persisted plan file", async () => {
    const planText = "Step 1: Read auth.py\nStep 2: Fix login flow";
    const { deps, fs } = buildDeps(planText);

    await handleImplement(deps);

    expect(fs.planContent).toBe(planText);
  });

  it("does not call writeFileSync", async () => {
    const planText = "Step 1: Read auth.py";
    const { deps } = buildDeps(planText);
    let writeCalled = false;
    deps.fs.writeFileSync = () => { writeCalled = true; };

    await handleImplement(deps);

    expect(writeCalled).toBe(false);
  });

  it("does not call mkdirSync", async () => {
    const planText = "Step 1: Read auth.py";
    const { deps } = buildDeps(planText);
    let mkdirCalled = false;
    deps.fs.mkdirSync = () => { mkdirCalled = true; };

    await handleImplement(deps);

    expect(mkdirCalled).toBe(false);
  });

  it("executes in strict order: read → enterPhase → newSession → setup → withSession", async () => {
    const planText = "Step 1: Read auth.py\nStep 2: Fix login flow";
    const { deps, enterPhaseCalls, newSession } = buildDeps(planText);

    const order: string[] = [];

    // Patch readFileSync to record the read step
    const originalRead = deps.fs.readFileSync;
    deps.fs.readFileSync = (path: string, options?: any) => {
      order.push("read");
      return originalRead(path, options);
    };

    // Patch enterPhase to record when it starts
    const originalEnterPhase = deps.enterPhase;
    deps.enterPhase = async (pi: any, ctx: any, phase: string) => {
      order.push("enterPhase");
      return originalEnterPhase(pi, ctx, phase);
    };

    // Patch newSession to record when it starts and its callbacks
    const originalNewSession = deps.newSession;
    deps.newSession = async (opts) => {
      order.push("newSession");
      if (opts?.setup) {
        const mockSm = {
          appendCustomMessageEntry: () => {},
        };
        await opts.setup(mockSm);
        order.push("setup");
      }
      if (opts?.withSession) {
        const mockCtx = {
          sendUserMessage: async () => {},
        };
        await opts.withSession(mockCtx);
        order.push("withSession");
      }
      return { cancelled: false };
    };

    await handleImplement(deps);

    expect(order).toEqual([
      "read",
      "enterPhase",
      "newSession",
      "setup",
      "withSession",
    ]);
    expect(enterPhaseCalls[0].phase).toBe("action");
  });
});

// ---------------------------------------------------------------------------
// issue #98 - /implement command registration
// ---------------------------------------------------------------------------

import planModeDefault from "./index.ts";

describe("issue #98 - /implement command registration", () => {
  function register() {
    let reg: { name: string; opts: any } | undefined;
    const pi = {
      registerCommand(name: string, opts: any) {
        reg = { name, opts };
      },
      registerShortcut: () => {},
      on: () => {},
    };
    planModeDefault(pi as any);
    if (!reg) throw new Error("no command registered");
    return reg;
  }

  it("registers a command named 'implement' with a description", () => {
    const reg = register();
    expect(reg.name).toBe("implement");
    expect(typeof reg.opts.description).toBe("string");
    expect(reg.opts.description.length).toBeGreaterThan(0);
    expect(typeof reg.opts.handler).toBe("function");
  });
});
