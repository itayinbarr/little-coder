import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import setupWriteGuard, { normalizeWritePath, isReservedDeviceName } from "./index.ts";

describe("normalizeWritePath", () => {
  const cwd = "/home/me/proj";

  it("rewrites /<bare-filename> to <cwd>/<bare-filename>", () => {
    // The model anchoring at filesystem root is the bug we're fixing.
    expect(normalizeWritePath("/foo.md", cwd)).toEqual({
      path: "/home/me/proj/foo.md",
      rewrittenFrom: "/foo.md",
    });
    expect(normalizeWritePath("/person.md", cwd)).toEqual({
      path: "/home/me/proj/person.md",
      rewrittenFrom: "/person.md",
    });
  });

  it("resolves bare filenames against cwd (no rewrite flag — already cwd-relative)", () => {
    expect(normalizeWritePath("foo.md", cwd)).toEqual({
      path: "/home/me/proj/foo.md",
    });
  });

  it("resolves nested relative paths against cwd", () => {
    expect(normalizeWritePath("sub/foo.md", cwd)).toEqual({
      path: "/home/me/proj/sub/foo.md",
    });
    expect(normalizeWritePath("a/b/c.md", cwd)).toEqual({
      path: "/home/me/proj/a/b/c.md",
    });
  });

  it("leaves genuine absolute paths alone (path has an intermediate directory)", () => {
    // /etc/hosts has an intermediate directory, so it's a legitimate
    // absolute path. We don't rewrite it.
    expect(normalizeWritePath("/etc/hosts", cwd)).toEqual({
      path: "/etc/hosts",
    });
    expect(normalizeWritePath("/tmp/foo.log", cwd)).toEqual({
      path: "/tmp/foo.log",
    });
  });

  it("leaves deep absolute paths in cwd untouched", () => {
    // Model handing back its own cwd-prefixed path: unchanged.
    expect(normalizeWritePath("/home/me/proj/notes/plan.md", cwd)).toEqual({
      path: "/home/me/proj/notes/plan.md",
    });
  });
});

// ── tool_call interceptor: the actual existing-file guard ───────────────────
// pi ships a built-in `write` that overwrites existing files and shadowed our
// old custom tool, so the guard never fired. We now enforce on the `tool_call`
// event, which catches whichever write implementation runs.

// write-guard registers TWO tool_call handlers — one for the `write` tool, one
// for shell tools (issue #70). Dispatch to both the way pi's runner does
// (core/extensions/runner.js::emitToolCall): run them in registration order and
// return the first result that blocks.
function getToolCallHandler() {
  const handlers: Array<(event: any, ctx: any) => any> = [];
  const pi = {
    on(name: string, h: (event: any, ctx: any) => any) {
      if (name === "tool_call") handlers.push(h);
    },
  };
  setupWriteGuard(pi as any);
  if (handlers.length === 0) throw new Error("write-guard did not register a tool_call handler");
  return async (event: any, ctx: any) => {
    let last: any;
    for (const h of handlers) {
      const result = await h(event, ctx);
      if (result) {
        last = result;
        if (result.block) return result;
      }
    }
    return last;
  };
}

function makeCtx(cwd: string) {
  const notifies: string[] = [];
  return { cwd, notifies, ui: { notify: (m: string) => notifies.push(m) } };
}

describe("write-guard tool_call interceptor", () => {
  let dir: string;
  let existing: string;
  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), "wg-"));
    existing = join(dir, "already.md");
    writeFileSync(existing, "old content\n");
  });
  afterEach(() => {
    rmSync(dir, { recursive: true, force: true });
  });

  it("blocks a write to an existing file with an Edit recipe", async () => {
    const handler = getToolCallHandler();
    const ctx = makeCtx(dir);
    const event = { toolName: "write", input: { path: existing, content: "new" } };
    const result = await handler(event, ctx);
    expect(result?.block).toBe(true);
    expect(result.reason).toContain("already exists");
    expect(result.reason).toContain('"name": "edit"'); // correct pi edit recipe
    expect(result.reason).toContain("oldText");
    expect(ctx.notifies[0]).toMatch(/harness intervention:.*redirected the model to Edit/i);
  });

  it("allows a write to a NEW file (no block) and normalizes the path in place", async () => {
    const handler = getToolCallHandler();
    const ctx = makeCtx(dir);
    const input: any = { path: "fresh.md", content: "hi" };
    const event = { toolName: "write", input };
    const result = await handler(event, ctx);
    expect(result).toBeUndefined();
    expect(input.path).toBe(join(dir, "fresh.md")); // normalized relative → cwd
    expect(ctx.notifies).toHaveLength(0);
  });

  it("rewrites a root-anchored /<bare> path to cwd in place", async () => {
    const handler = getToolCallHandler();
    const ctx = makeCtx(dir);
    const input: any = { path: "/fresh.md", content: "hi" };
    await handler({ toolName: "write", input }, ctx);
    expect(input.path).toBe(join(dir, "fresh.md"));
  });

  it("honors the file_path arg key as well as path", async () => {
    const handler = getToolCallHandler();
    const ctx = makeCtx(dir);
    const result = await handler(
      { toolName: "write", input: { file_path: existing, content: "x" } },
      ctx,
    );
    expect(result?.block).toBe(true);
  });

  it("is case-insensitive on the tool name", async () => {
    const handler = getToolCallHandler();
    const ctx = makeCtx(dir);
    const result = await handler({ toolName: "Write", input: { path: existing } }, ctx);
    expect(result?.block).toBe(true);
  });

  it("ignores non-write tools", async () => {
    const handler = getToolCallHandler();
    const ctx = makeCtx(dir);
    const result = await handler({ toolName: "read", input: { path: existing } }, ctx);
    expect(result).toBeUndefined();
  });

  it("ignores a write call with no path argument", async () => {
    const handler = getToolCallHandler();
    const ctx = makeCtx(dir);
    const result = await handler({ toolName: "write", input: { content: "x" } }, ctx);
    expect(result).toBeUndefined();
  });

  it("blocks a write to a reserved Windows device name (issue #60)", async () => {
    const handler = getToolCallHandler();
    const ctx = makeCtx(dir);
    // Bare `nul` — the model treating it like /dev/null. On Windows this would
    // create an undeletable device-named file; we refuse on every platform.
    const result = await handler({ toolName: "write", input: { path: "nul", content: "x" } }, ctx);
    expect(result?.block).toBe(true);
    expect(result.reason).toContain("reserved Windows device name");
    expect(ctx.notifies[0]).toMatch(/reserved device name/i);
  });

  it("blocks reserved device names with an extension and any case", async () => {
    const handler = getToolCallHandler();
    const ctx = makeCtx(dir);
    for (const name of ["NUL.txt", "Com1", "lpt9.log", "AUX", "con"]) {
      const result = await handler({ toolName: "write", input: { path: name, content: "x" } }, ctx);
      expect(result?.block, `${name} should be blocked`).toBe(true);
    }
  });

  it("allows normal filenames that merely contain a reserved stem", async () => {
    const handler = getToolCallHandler();
    const ctx = makeCtx(dir);
    // `nullable.ts` / `console.log` are NOT reserved — only the exact stem is.
    for (const name of ["nullable.ts", "console.log", "auxiliary.md", "lpt.md"]) {
      const result = await handler({ toolName: "write", input: { path: name, content: "x" } }, ctx);
      expect(result, `${name} should pass`).toBeUndefined();
    }
  });
});

// ── Issue #70: the shell is the same write ─────────────────────────────────
// Once `write` was refused, Qwen switched to `cat > file << 'EOF'` and got the
// bytes anyway — the guard only ever looked at the `write` tool, and
// `ShellSession` wasn't gated at all.

describe("write-guard shell interceptor (issue #70)", () => {
  let dir: string;
  let existing: string;
  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), "wg-sh-"));
    existing = join(dir, "main.py");
    writeFileSync(existing, "old content\n");
  });
  afterEach(() => {
    rmSync(dir, { recursive: true, force: true });
  });

  it("blocks rvanswieten's exact heredoc rewrite of an existing file", async () => {
    const handler = getToolCallHandler();
    const ctx = makeCtx(dir);
    const command = [
      "cat > main.py << 'ENDOFFILE'",
      "from fastapi import FastAPI",
      "ENDOFFILE",
    ].join("\n");
    const result = await handler({ toolName: "ShellSession", input: { command } }, ctx);
    expect(result?.block).toBe(true);
    expect(result.reason).toContain("already exists");
    expect(result.reason).toContain('"name": "edit"');
    expect(ctx.notifies[0]).toMatch(/harness intervention:.*redirected the model to Edit/i);
  });

  it("blocks it through the bash tool too, and under a different delimiter", async () => {
    const handler = getToolCallHandler();
    for (const toolName of ["bash", "Bash", "ShellSession"]) {
      const command = `cat > main.py << 'MY_OWN_MARKER'\nx\nMY_OWN_MARKER`;
      const result = await handler({ toolName, input: { command } }, makeCtx(dir));
      expect(result?.block, toolName).toBe(true);
    }
  });

  it("blocks a plain truncating redirect and a tee onto an existing file", async () => {
    const handler = getToolCallHandler();
    for (const command of ["echo hi > main.py", "echo hi | tee main.py"]) {
      const result = await handler({ toolName: "bash", input: { command } }, makeCtx(dir));
      expect(result?.block, command).toBe(true);
    }
  });

  it("allows an append to an existing file — nothing is destroyed", async () => {
    const handler = getToolCallHandler();
    const result = await handler(
      { toolName: "bash", input: { command: "echo hi >> main.py" } },
      makeCtx(dir),
    );
    expect(result).toBeUndefined();
  });

  it("allows a redirect that creates a NEW file", async () => {
    const handler = getToolCallHandler();
    const result = await handler(
      { toolName: "bash", input: { command: "echo hi > brand-new.txt" } },
      makeCtx(dir),
    );
    expect(result).toBeUndefined();
  });

  it("blocks a redirect to a reserved device name even as an append", async () => {
    const handler = getToolCallHandler();
    const result = await handler(
      { toolName: "bash", input: { command: "echo hi >> nul" } },
      makeCtx(dir),
    );
    expect(result?.block).toBe(true);
    expect(result.reason).toContain("reserved Windows device name");
  });

  it("leaves read-only shell commands alone", async () => {
    const handler = getToolCallHandler();
    for (const command of ["ls -la", "cat main.py", "make 2>&1", 'grep "a > b" main.py']) {
      const result = await handler({ toolName: "bash", input: { command } }, makeCtx(dir));
      expect(result, command).toBeUndefined();
    }
  });

  it("ignores shell tools that carry no command", async () => {
    const handler = getToolCallHandler();
    const result = await handler({ toolName: "ShellSession", input: {} }, makeCtx(dir));
    expect(result).toBeUndefined();
  });
});

describe("isReservedDeviceName", () => {
  it("matches reserved device names regardless of case or extension", () => {
    for (const name of ["nul", "NUL", "Nul.txt", "con", "PRN", "aux", "com1", "COM9.log", "lpt1", "lpt9.dat"]) {
      expect(isReservedDeviceName(name), name).toBe(true);
      expect(isReservedDeviceName(`/home/me/proj/${name}`), name).toBe(true);
    }
  });
  it("does not match normal names that merely start with a reserved stem", () => {
    for (const name of ["nullable.ts", "console.log", "auxiliary", "com10", "lpt0", "comm", "null.d/real.txt"]) {
      expect(isReservedDeviceName(name), name).toBe(false);
    }
  });
});
