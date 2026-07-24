import { afterEach, describe, expect, it } from "vitest";
import setupSkillInject from "./index.ts";
import setupKnowledgeInject from "../knowledge-inject/index.ts";

// End-to-end check of the #73 conversion: drive the real `before_agent_start`
// handlers of both injectors, against the real skills/ files, and assert the
// guidance still gets delivered — just at the conversation tail instead of
// stapled onto the system prompt.

type Handler = (event: any, ctx: any) => Promise<any>;

function handlerFor(setup: (pi: any) => void): Handler {
  let handler: Handler | undefined;
  setup({
    on(name: string, h: Handler) {
      if (name === "before_agent_start") handler = h;
    },
  });
  if (!handler) throw new Error("extension registered no before_agent_start handler");
  return handler;
}

const ctx = { ui: { notify: () => {} } };

/** A turn event with the little-coder budgets the extensions expect. */
function turn(prompt: string, systemPrompt = "BASE SYSTEM PROMPT") {
  return {
    prompt,
    systemPrompt,
    systemPromptOptions: {
      littleCoder: { skillTokenBudget: 300, knowledgeTokenBudget: 200, contextLimit: 32768 },
    },
  };
}

afterEach(() => {
  delete process.env.LITTLE_CODER_INJECT_MODE;
});

describe("skill-inject still injects after the #73 conversion", () => {
  it("delivers the tool skill cards as a hidden tail message", async () => {
    const handler = handlerFor(setupSkillInject);
    const result = await handler(turn("edit the parser to fix the bug"), ctx);

    expect(result?.message).toBeDefined();
    expect(result.message.customType).toBe("lc-skills");
    expect(result.message.display).toBe(false);
    expect(result.message.content).toContain("## Tool Usage Guidance");
    // The cached prefix must come through untouched.
    expect(result.systemPrompt).toBeUndefined();
  });

  it("still appends the research directive last, ahead of nothing", async () => {
    const handler = handlerFor(setupSkillInject);
    const result = await handler(turn("research the history of the transistor online"), ctx);
    const content: string = result.message.content;
    expect(content).toContain("## Research-first directive");
    // Recency bias is the reason the directive is last; keep that ordering.
    expect(content.indexOf("## Research-first directive")).toBeGreaterThan(
      content.indexOf("## Tool Usage Guidance"),
    );
  });

  it("skips a repeat of the identical block on the next turn", async () => {
    const handler = handlerFor(setupSkillInject);
    const first = await handler(turn("edit the parser"), ctx);
    expect(first?.message).toBeDefined();
    // Same prompt shape → same selection → the copy from turn 1 is still there.
    const second = await handler(turn("edit the parser"), ctx);
    expect(second).toBeUndefined();
  });

  it("falls back to the system prompt under LITTLE_CODER_INJECT_MODE=system", async () => {
    process.env.LITTLE_CODER_INJECT_MODE = "system";
    const handler = handlerFor(setupSkillInject);
    const result = await handler(turn("edit the parser to fix the bug"), ctx);

    expect(result?.message).toBeUndefined();
    expect(result.systemPrompt.startsWith("BASE SYSTEM PROMPT")).toBe(true);
    expect(result.systemPrompt).toContain("## Tool Usage Guidance");
  });

  it("stays silent when nothing matches", async () => {
    const handler = handlerFor(setupSkillInject);
    expect(await handler(turn("zzzz"), ctx)).toBeUndefined();
  });
});

describe("knowledge-inject still injects after the #73 conversion", () => {
  // Scoring is word=1.0 / phrase=2.0 against MIN_SCORE_THRESHOLD=2.0, so the
  // prompt needs one phrase keyword or two single-word ones from a shipped
  // skills/knowledge entry. "dynamic programming" is a phrase keyword of
  // skills/knowledge/dynamic_programming.md.
  const PROMPT = "use dynamic programming to memoize this subproblem";

  async function inject(handler: Handler) {
    return handler(turn(PROMPT), ctx);
  }

  it("delivers algorithm reference entries as a hidden tail message", async () => {
    const handler = handlerFor(setupKnowledgeInject);
    const result = await inject(handler);

    expect(result, "no knowledge entry scored above threshold").toBeDefined();
    expect(result.message.customType).toBe("lc-knowledge");
    expect(result.message.display).toBe(false);
    expect(result.message.content).toContain("## Algorithm Reference");
    expect(result.systemPrompt).toBeUndefined();
  });

  it("falls back to the system prompt under LITTLE_CODER_INJECT_MODE=system", async () => {
    process.env.LITTLE_CODER_INJECT_MODE = "system";
    const handler = handlerFor(setupKnowledgeInject);
    const result = await inject(handler);

    expect(result, "no knowledge entry scored above threshold").toBeDefined();
    expect(result.message).toBeUndefined();
    expect(result.systemPrompt.startsWith("BASE SYSTEM PROMPT")).toBe(true);
    expect(result.systemPrompt).toContain("## Algorithm Reference");
  });
});
