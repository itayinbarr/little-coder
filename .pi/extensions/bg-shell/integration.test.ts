import { describe, it, expect, afterEach } from "vitest";
import { execFileSync } from "node:child_process";
import setupBgShell, { reapAll } from "./index.ts";

// Drives the real extension against real processes. The pure-logic tests in
// jobs.test.ts cover the wake rules; everything that can only break against an
// actual OS — stream framing, exit plumbing, and killing a process TREE rather
// than just the shell we spawned — is covered here.

interface Sent {
  content: string;
  delivery: any;
}

function wire() {
  const sent: Sent[] = [];
  const tools: Record<string, any> = {};
  const handlers: Record<string, any> = {};
  const pi: any = {
    registerTool: (t: any) => { tools[t.name] = t; },
    on: (n: string, h: any) => { handlers[n] = h; },
    sendMessage: (msg: any, delivery: any) => { sent.push({ content: msg.content, delivery }); },
  };
  setupBgShell(pi);
  const ctx = { hasUI: false, ui: {} };
  const call = (name: string, params: any) =>
    tools[name].execute("id", params, undefined, undefined, ctx);
  return { sent, tools, handlers, call };
}

const textOf = (r: any) => r.content[0].text as string;

/** Poll until `fn()` is true or the deadline passes. `fn` may be async — the
 *  tools all return promises, and treating one as a value silently reads
 *  `undefined.content`. */
async function until(fn: () => boolean | Promise<boolean>, ms = 8000): Promise<boolean> {
  const deadline = Date.now() + ms;
  while (Date.now() < deadline) {
    try {
      if (await fn()) return true;
    } catch {
      /* not ready yet */
    }
    await new Promise((r) => setTimeout(r, 50));
  }
  try {
    return await fn();
  } catch {
    return false;
  }
}

function pidAlive(pid: number): boolean {
  try {
    process.kill(pid, 0);
    return true;
  } catch {
    return false;
  }
}

afterEach(() => {
  reapAll();
});

describe("bg-shell against real processes", () => {
  const T = 20_000;
  it("starts a job, buffers its output, and wakes on clean exit", async () => {
    const { sent, call } = wire();
    const started = textOf(await call("ShellStart", {
      command: "echo first; echo second; exit 0",
      label: "quick",
    }));
    expect(started).toContain("Started \"quick\"");
    // The description promises the model it does not need to poll; the start
    // message must say so too or the model will poll anyway.
    expect(started).toContain("do not poll");

    expect(await until(() => sent.length > 0)).toBe(true);
    const wake = sent[0];
    expect(wake.content).toContain("exited 0");
    expect(wake.content).toContain("second");
    // A clean exit is worth delivering, not worth interrupting a tool call for.
    expect(wake.delivery).toEqual({ deliverAs: "followUp", triggerTurn: true });
  }, T);

  it("gives a crash the urgent lane", async () => {
    const { sent, call } = wire();
    await call("ShellStart", { command: "echo boom >&2; exit 3", label: "crash" });
    expect(await until(() => sent.length > 0)).toBe(true);
    expect(sent[0].content).toContain("exited 3");
    expect(sent[0].delivery).toEqual({ deliverAs: "steer", triggerTurn: true });
  }, T);

  it("stays silent for a job whose rules match nothing", async () => {
    const { sent, call } = wire();
    await call("ShellStart", {
      command: "echo tick; echo tock; sleep 0.2",
      label: "quiet",
      wake_on: { exit: false, match: ["Traceback"] },
    });
    await new Promise((r) => setTimeout(r, 900));
    // The core promise: routine output costs zero turns.
    expect(sent).toEqual([]);
  }, T);

  it("wakes on a matched pattern while the job is still running", async () => {
    const { sent, call } = wire();
    await call("ShellStart", {
      command: "echo warming; echo 'Traceback (most recent call last)'; sleep 2",
      label: "trainer",
      wake_on: { exit: false, match: ["Traceback"] },
    });
    expect(await until(() => sent.length > 0)).toBe(true);
    expect(sent[0].content).toContain("matched");
    expect(sent[0].content).toContain("still running");
    expect(sent[0].delivery.deliverAs).toBe("steer"); // Traceback is error-ish
  }, T);

  it("reads back a slice of the log on demand", async () => {
    const { call } = wire();
    const id = textOf(await call("ShellStart", {
      command: "for i in 1 2 3 4 5; do echo line$i; done; exit 0",
      label: "counter",
    })).match(/as (job\d+)/)![1];

    await new Promise((r) => setTimeout(r, 600));

    const log = textOf(await call("ShellLog", { id, lines: 3 }));
    expect(log).toContain("line5");
    expect(log).not.toContain("line1"); // tail of 3 only
  }, T);

  it("writes to a running job's stdin", async () => {
    const { call } = wire();
    const id = textOf(await call("ShellStart", {
      command: "read x; echo got:$x; exit 0",
      label: "reader",
    })).match(/as (job\d+)/)![1];

    await new Promise((r) => setTimeout(r, 300));
    await call("ShellSend", { id, text: "hello" });
    await new Promise((r) => setTimeout(r, 500));
    expect(textOf(await call("ShellLog", { id }))).toContain("got:hello");
  });

  // The one that matters most. `python train.py` runs as a GRANDCHILD under the
  // bash we spawn — killing only the shell would orphan the process actually
  // holding the GPU. Spawning detached and signalling the group is what makes
  // this pass.
  it("ShellStop kills the whole process tree, not just the shell", async () => {
    const { call } = wire();
    const id = textOf(await call("ShellStart", {
      command: "sleep 300 & echo GRANDCHILD=$!; wait",
      label: "tree",
    })).match(/as (job\d+)/)![1];

    expect(await until(async () => textOf(await call("ShellLog", { id })).includes("GRANDCHILD="))).toBe(true);
    const grandchild = Number(
      textOf(await call("ShellLog", { id })).match(/GRANDCHILD=(\d+)/)![1],
    );
    expect(pidAlive(grandchild)).toBe(true);

    await call("ShellStop", { id });
    expect(await until(() => !pidAlive(grandchild), 8000)).toBe(true);
  }, T);

  it("reapAll leaves nothing running", async () => {
    const { call } = wire();
    const id = textOf(await call("ShellStart", {
      command: "sleep 300 & echo GRANDCHILD=$!; wait",
      label: "leak",
    })).match(/as (job\d+)/)![1];
    expect(await until(async () => textOf(await call("ShellLog", { id })).includes("GRANDCHILD="))).toBe(true);
    const grandchild = Number(
      textOf(await call("ShellLog", { id })).match(/GRANDCHILD=(\d+)/)![1],
    );

    reapAll();
    expect(await until(() => !pidAlive(grandchild), 8000)).toBe(true);
  }, T);

  it("refuses to start more than the job cap", async () => {
    const { call } = wire();
    for (let i = 0; i < 8; i++) await call("ShellStart", { command: "sleep 30", label: `j${i}` });
    const over = await call("ShellStart", { command: "sleep 30", label: "over" });
    expect(over.isError).toBe(true);
    expect(textOf(over)).toContain("max 8");
  }, T);

  it("reports unknown job ids rather than throwing", async () => {
    const { call } = wire();
    for (const tool of ["ShellLog", "ShellSend", "ShellStop"]) {
      const r = await call(tool, { id: "nope", text: "x" });
      expect(r.isError, tool).toBe(true);
      expect(textOf(r)).toContain("no such job");
    }
  }, T);
});

describe("the parent watchdog", () => {
  // The backstop for SIGKILL, which no signal handler can catch. A job must die
  // when little-coder dies by ANY means, or a training run keeps 8GB of VRAM.
  // Simulated with a throwaway parent so the test can SIGKILL it safely.
  it("kills the job when its parent disappears without warning", async () => {
    const { wrapWithParentWatchdog } = await import("./jobs.ts");

    // A stand-in "little-coder" that does nothing but stay alive.
    const parent = execFileSync("bash", ["-c", "sleep 120 >/dev/null 2>&1 & echo $!"])
      .toString().trim();
    const parentPid = Number(parent);

    const script = wrapWithParentWatchdog("sleep 120 & echo CHILD=$!; wait", parentPid, 1);
    const { spawn } = await import("node:child_process");
    const proc = spawn(script, { shell: "/bin/bash", detached: true, stdio: ["ignore", "pipe", "pipe"] });

    let out = "";
    proc.stdout.on("data", (d) => { out += d.toString(); });
    expect(await until(() => /CHILD=\d+/.test(out))).toBe(true);
    const child = Number(out.match(/CHILD=(\d+)/)![1]);
    expect(pidAlive(child)).toBe(true);

    // Hard-kill the parent: no handler runs, nothing gets a chance to clean up.
    process.kill(parentPid, "SIGKILL");

    // The watchdog polls at 1s here, so this resolves quickly.
    expect(await until(() => !pidAlive(child), 15_000)).toBe(true);

    try { process.kill(-proc.pid!, "SIGKILL"); } catch { /* already gone */ }
  }, 25_000);
});

describe("wake coalescing", () => {
  // A crash prints its traceback and dies milliseconds later. Waking once for
  // the matched line and again for the exit costs two turns to learn one thing,
  // which is the exact waste this feature exists to remove.
  it("sends one message when a matched line is immediately followed by exit", async () => {
    const { sent, call } = wire();
    await call("ShellStart", {
      command: "echo 'Traceback (most recent call last)'; exit 1",
      label: "crasher",
      wake_on: { match: ["Traceback"] },
    });
    await new Promise((r) => setTimeout(r, 3000));
    expect(sent.length).toBe(1);
    expect(sent[0].content).toContain("exited 1"); // the exit wake, not the match
    expect(sent[0].content).toContain("Traceback"); // still carries the excerpt
  }, 20_000);

  // But a match on a job that keeps running must still arrive.
  it("still delivers a match wake when the job stays alive", async () => {
    const { sent, call } = wire();
    await call("ShellStart", {
      command: "echo 'Traceback here'; sleep 5",
      label: "survivor",
      wake_on: { match: ["Traceback"] },
    });
    await new Promise((r) => setTimeout(r, 3000));
    expect(sent.length).toBe(1);
    expect(sent[0].content).toContain("matched");
    expect(sent[0].content).toContain("still running");
  }, 20_000);
});
