import { describe, it, expect } from "vitest";
import { spawn } from "node:child_process";
import {
  buildChildEnv,
  defaultConcurrency,
  getFinalText,
  resolveLauncher,
  scheduleForceKill,
  summarizeActivity,
  truncateReport,
  SUBCODER_ALLOWED_TOOLS,
  type SubCoderResult,
} from "./spawn.ts";

describe("scheduleForceKill", () => {
  it("SIGKILLs a child that ignores SIGTERM (proc.killed would have blocked it)", async () => {
    // Trap SIGTERM and stay alive — only SIGKILL can end this child. Print
    // "ready" AFTER registering the handler so the parent doesn't race the
    // SIGTERM in before the trap is installed (which would kill it by default).
    const child = spawn(process.execPath, [
      "-e",
      "process.on('SIGTERM',()=>{});console.log('ready');setInterval(()=>{},1000)",
    ]);
    await new Promise<void>((r) => {
      child.stdout.on("data", (d) => {
        if (d.toString().includes("ready")) r();
      });
    });

    child.kill("SIGTERM");
    // Node flips `killed` true on dispatch even though the child is still alive —
    // this is exactly the condition that made the old `if (!proc.killed)` dead.
    expect(child.killed).toBe(true);

    let exited = false;
    child.once("exit", () => (exited = true));
    scheduleForceKill(child, () => exited, 50);

    const signal = await new Promise<NodeJS.Signals | null>((r) =>
      child.once("exit", (_code, sig) => r(sig)),
    );
    expect(signal).toBe("SIGKILL");
  });

  it("does not force-kill a child that has already exited", async () => {
    let killed = false;
    const fake = { kill: () => (killed = true) };
    await new Promise((r) => {
      scheduleForceKill(fake as any, () => true, 5);
      setTimeout(r, 30);
    });
    expect(killed).toBe(false);
  });
});

const base: SubCoderResult = {
  id: "1",
  label: "x",
  task: "t",
  exitCode: -1,
  report: "",
  messages: [],
  stderr: "",
  usage: { input: 0, output: 0, cost: 0, turns: 0, contextTokens: 0 },
};

describe("getFinalText", () => {
  it("returns the last assistant text block", () => {
    const messages = [
      { role: "assistant", content: [{ type: "text", text: "first" }] },
      { role: "assistant", content: [{ type: "toolCall", name: "read", arguments: {} }] },
      { role: "assistant", content: [{ type: "text", text: "final answer" }] },
    ];
    expect(getFinalText(messages)).toBe("final answer");
  });
  it("returns empty string when there is no assistant text", () => {
    expect(getFinalText([{ role: "user", content: [{ type: "text", text: "hi" }] }])).toBe("");
    expect(getFinalText([])).toBe("");
  });
});

describe("truncateReport", () => {
  it("leaves short reports intact", () => {
    expect(truncateReport("short")).toBe("short");
  });
  it("truncates long reports with a notice", () => {
    const out = truncateReport("a".repeat(5000), 100);
    expect(out.length).toBeLessThan(300);
    expect(out).toContain("truncated at 100 chars");
  });
});

describe("summarizeActivity", () => {
  it("shows the report's first line when done", () => {
    expect(summarizeActivity({ ...base, exitCode: 0, report: "Found 3 routes\nmore" })).toBe("Found 3 routes");
  });
  it("surfaces the latest tool call while running", () => {
    const r = {
      ...base,
      messages: [{ role: "assistant", content: [{ type: "toolCall", name: "grep", arguments: { pattern: "login(" } }] }],
    };
    expect(summarizeActivity(r)).toBe("→ grep login(");
  });
  it("shows the error message on failure", () => {
    expect(summarizeActivity({ ...base, exitCode: 1, errorMessage: "boom" })).toBe("boom");
  });
  it("falls back to working when running with no tool call", () => {
    expect(summarizeActivity(base)).toBe("working…");
  });
  it("caps long error messages on failure (issue #48 regression)", () => {
    const longErr =
      "child process exited with non-zero code 1: " +
      "Error: provider \"llamacpp\" — failed to reach " +
      "http://127.0.0.1:8888/v1/chat/completions: ECONNREFUSED";
    const out = summarizeActivity({ ...base, exitCode: 1, errorMessage: longErr });
    expect(out.length).toBeLessThanOrEqual(56);
    expect(out.endsWith("…")).toBe(true);
  });
});

describe("buildChildEnv", () => {
  it("constrains the child to read-only tools and the headless fast-path", () => {
    const env = buildChildEnv();
    expect(env.LITTLE_CODER_ALLOWED_TOOLS).toBe(SUBCODER_ALLOWED_TOOLS);
    expect(env.LITTLE_CODER_ALLOWED_TOOLS).not.toContain("edit");
    expect(env.LITTLE_CODER_ALLOWED_TOOLS).not.toContain("write");
    expect(env.LITTLE_CODER_ALLOWED_TOOLS).not.toContain("dispatch");
    expect(env.LITTLE_CODER_PERMISSION_MODE).toBe("auto");
    expect(env.LITTLE_CODER_SUBAGENT).toBe("1");
  });
  it("merges extra overrides", () => {
    expect(buildChildEnv({ FOO: "bar" }).FOO).toBe("bar");
  });
});

describe("resolveLauncher / defaultConcurrency", () => {
  it("points at bin/little-coder.mjs", () => {
    expect(resolveLauncher().replace(/\\/g, "/")).toMatch(/\/bin\/little-coder\.mjs$/);
  });
  it("defaults concurrency to 1 (serial) and honors explicit values incl. 0 (issue #57)", () => {
    const prev = process.env.LITTLE_CODER_SUBCODER_CONCURRENCY;
    const set = (v?: string) => {
      if (v === undefined) delete process.env.LITTLE_CODER_SUBCODER_CONCURRENCY;
      else process.env.LITTLE_CODER_SUBCODER_CONCURRENCY = v;
    };

    set(undefined);
    expect(defaultConcurrency()).toBe(1); // unset → serial default
    set("");
    expect(defaultConcurrency()).toBe(1); // empty → serial default
    set("3");
    expect(defaultConcurrency()).toBe(3); // explicit opt-in to parallelism
    set("0");
    expect(defaultConcurrency()).toBe(1); // 0 means "serial", not "fall back to default"
    set("-3");
    expect(defaultConcurrency()).toBe(1); // negatives clamp to serial
    set("not-a-number");
    expect(defaultConcurrency()).toBe(1); // garbage → serial default
    set("2.9");
    expect(defaultConcurrency()).toBe(2); // floored

    set(prev);
  });
});
