import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { mkdtempSync, rmSync, writeFileSync, existsSync, readdirSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import setupCheckpoint, { checkpointPath, tracked } from "./index.ts";

describe("checkpointPath", () => {
  it("reads the `path` key (current pi write/edit)", () => {
    expect(checkpointPath({ path: "/a/b.ts" })).toBe("/a/b.ts");
  });
  it("falls back to the legacy `file_path` key", () => {
    expect(checkpointPath({ file_path: "/a/c.ts" })).toBe("/a/c.ts");
  });
  it("prefers `path` when both are present", () => {
    expect(checkpointPath({ path: "/p", file_path: "/f" })).toBe("/p");
  });
  it("returns undefined when neither is a string", () => {
    expect(checkpointPath({})).toBeUndefined();
    expect(checkpointPath({ path: 5 as unknown as string })).toBeUndefined();
  });
});

function setup() {
  const handlers: Record<string, (...args: any[]) => any> = {};
  const pi = {
    on(name: string, h: (...args: any[]) => any) {
      handlers[name] = h;
    },
  };
  setupCheckpoint(pi as any);
  return handlers;
}

// homedir() honors $HOME on POSIX, so pointing it at a tmpdir isolates the
// ~/.little-coder/checkpoints/ writes the backup net makes.
describe("checkpoint pre-edit backup net", () => {
  let home: string;
  let origHome: string | undefined;
  beforeEach(() => {
    origHome = process.env.HOME;
    home = mkdtempSync(join(tmpdir(), "ckpt-"));
    process.env.HOME = home;
    tracked.clear();
  });
  afterEach(() => {
    if (origHome === undefined) delete process.env.HOME;
    else process.env.HOME = origHome;
    rmSync(home, { recursive: true, force: true });
  });

  it("snapshots a file modified via the `path` key (regression: previously never fired)", async () => {
    const h = setup();
    const target = join(home, "src.txt");
    writeFileSync(target, "original");
    await h.session_start({}, { sessionManager: { getSessionFile: () => "/x/sess-123.json" } });
    await h.tool_call({ toolName: "write", input: { path: target, content: "new" } });

    const dir = join(home, ".little-coder", "checkpoints", "sess-123.json");
    expect(existsSync(dir)).toBe(true);
    expect(readdirSync(dir).length).toBe(1);
  });

  it("also snapshots via the legacy `file_path` key", async () => {
    const h = setup();
    const target = join(home, "src2.txt");
    writeFileSync(target, "orig");
    await h.session_start({}, { sessionManager: { getSessionFile: () => "/x/sess-9.json" } });
    await h.tool_call({ toolName: "Edit", input: { file_path: target, edits: [] } });

    expect(existsSync(join(home, ".little-coder", "checkpoints", "sess-9.json"))).toBe(true);
  });

  it("ignores tool calls that carry no path", async () => {
    const h = setup();
    await h.session_start({}, { sessionManager: { getSessionFile: () => "/x/sess-0.json" } });
    await h.tool_call({ toolName: "write", input: { content: "no path here" } });
    expect(existsSync(join(home, ".little-coder", "checkpoints", "sess-0.json"))).toBe(false);
  });
});
