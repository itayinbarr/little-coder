import { describe, it, expect } from "vitest";
import setupPermissionGate, {
  isSafeBash,
  parseExtraPrefixes,
  getSafePrefixes,
} from "./index.ts";

describe("isSafeBash", () => {
  it("allows whitelisted read-only commands", () => {
    expect(isSafeBash("ls -la")).toBe(true);
    expect(isSafeBash("cat /etc/hosts")).toBe(true);
    expect(isSafeBash("git log --oneline")).toBe(true);
    expect(isSafeBash("grep -r pattern .")).toBe(true);
    expect(isSafeBash("rg pattern src/")).toBe(true);
    expect(isSafeBash("sed -n '1,20p' file.ts")).toBe(true);
  });
  it("allows routine filesystem scaffolding (cp/mv/mkdir/touch)", () => {
    expect(isSafeBash("cp a b")).toBe(true);
    expect(isSafeBash("mv old new")).toBe(true);
    expect(isSafeBash("mkdir -p sub/dir")).toBe(true);
    expect(isSafeBash("touch foo.md")).toBe(true);
  });
  it("preserves trailing-whitespace word boundary on fs prefixes", () => {
    // Without the trailing space, "cp" would match "cpufetch". With it, these stay blocked.
    expect(isSafeBash("cpufetch")).toBe(false);
    expect(isSafeBash("mvtool")).toBe(false);
    expect(isSafeBash("mkdiroops")).toBe(false);
    expect(isSafeBash("touchscreen")).toBe(false);
  });
  it("blocks non-whitelisted commands", () => {
    expect(isSafeBash("rm -rf /")).toBe(false);
    expect(isSafeBash("npm install foo")).toBe(false);
    expect(isSafeBash("sudo anything")).toBe(false);
  });
  it("handles leading whitespace", () => {
    expect(isSafeBash("   ls")).toBe(true);
  });
  it("git subcommand gating is strict", () => {
    expect(isSafeBash("git log")).toBe(true);
    expect(isSafeBash("git push origin main")).toBe(false);
    expect(isSafeBash("git commit -m x")).toBe(false);
  });
  it("respects an explicit prefix list (LITTLE_CODER_BASH_ALLOW shape)", () => {
    const extra = ["make ", "docker compose ps"];
    expect(isSafeBash("make test", extra)).toBe(true);
    expect(isSafeBash("docker compose ps", extra)).toBe(true);
    expect(isSafeBash("docker compose down", extra)).toBe(false);
  });
});

// ── Issue #70 ──────────────────────────────────────────────────────────────
// The old check was `command.trim().startsWith(prefix)` on the raw string, so
// it only ever judged the first command and had no idea a `>` was sitting
// right after a whitelisted one.

describe("isSafeBash hardening (issue #70)", () => {
  it("refuses a whitelisted command that redirects into a file", () => {
    // rvanswieten's repro: "cat" is whitelisted, and the check was startsWith.
    expect(isSafeBash("cat > backend/main.py << 'ENDOFFILE'\nbody\nENDOFFILE")).toBe(false);
    expect(isSafeBash("echo hi > notes.txt")).toBe(false);
    expect(isSafeBash("echo hi >> notes.txt")).toBe(false);
    expect(isSafeBash("cat a | tee b.txt")).toBe(false);
  });

  it("judges every command in a chain, not just the first", () => {
    expect(isSafeBash("ls && rm -rf /")).toBe(false);
    expect(isSafeBash("ls ; npm install foo")).toBe(false);
    expect(isSafeBash("cat f | sudo tee /etc/hosts")).toBe(false);
    // …and still allows a chain where every link is whitelisted.
    expect(isSafeBash("ls && git status")).toBe(true);
    expect(isSafeBash("cat f | grep x | wc -l")).toBe(true);
  });

  it("does not trip over redirect-shaped text that writes nothing", () => {
    expect(isSafeBash("make 2>&1", ["make "])).toBe(true);
    expect(isSafeBash('grep "a > b" file.txt')).toBe(true);
    expect(isSafeBash("wc -l < input.txt")).toBe(true);
  });

  it("refuses an empty command", () => {
    expect(isSafeBash("")).toBe(false);
    expect(isSafeBash("   ")).toBe(false);
  });
});

describe("permission-gate tool_call interceptor", () => {
  function getHandler() {
    let handler: ((event: any, ctx: any) => any) | undefined;
    setupPermissionGate({
      on(name: string, h: (event: any, ctx: any) => any) {
        if (name === "tool_call") handler = h;
      },
    } as any);
    if (!handler) throw new Error("permission-gate registered no tool_call handler");
    return handler;
  }

  function withMode<T>(mode: string | undefined, fn: () => T): T {
    const prev = process.env.LITTLE_CODER_PERMISSION_MODE;
    if (mode === undefined) delete process.env.LITTLE_CODER_PERMISSION_MODE;
    else process.env.LITTLE_CODER_PERMISSION_MODE = mode;
    try {
      return fn();
    } finally {
      if (prev === undefined) delete process.env.LITTLE_CODER_PERMISSION_MODE;
      else process.env.LITTLE_CODER_PERMISSION_MODE = prev;
    }
  }

  it("gates ShellSession, which used to reach execSync with no gate at all", async () => {
    const handler = getHandler();
    await withMode("auto", async () => {
      const result = await handler(
        { toolName: "ShellSession", input: { command: "rm -rf /" } },
        {},
      );
      expect(result?.block).toBe(true);
    });
  });

  it("explains a shell-redirect refusal in terms the model can act on", async () => {
    const handler = getHandler();
    await withMode("auto", async () => {
      const result = await handler(
        { toolName: "ShellSession", input: { command: "cat > main.py << 'EOF'\nx\nEOF" } },
        {},
      );
      expect(result?.block).toBe(true);
      expect(result.reason).toContain("main.py");
      expect(result.reason).toMatch(/Write tool|Edit/);
    });
  });

  it("names the offending command in a chain, not the harmless first one", async () => {
    const handler = getHandler();
    await withMode("auto", async () => {
      const result = await handler(
        { toolName: "bash", input: { command: "ls && npm install left-pad" } },
        {},
      );
      expect(result?.block).toBe(true);
      expect(result.reason).toContain("npm");
      expect(result.reason).not.toContain('"ls"');
    });
  });

  it("still lets whitelisted commands through on every shell tool", async () => {
    const handler = getHandler();
    await withMode("auto", async () => {
      for (const toolName of ["bash", "Bash", "ShellSession"]) {
        const result = await handler({ toolName, input: { command: "git status" } }, {});
        expect(result, toolName).toBeUndefined();
      }
    });
  });

  it("leaves the no-command shell helpers ungated", async () => {
    const handler = getHandler();
    await withMode("auto", async () => {
      for (const toolName of ["ShellSessionCwd", "ShellSessionReset"]) {
        expect(await handler({ toolName, input: {} }, {}), toolName).toBeUndefined();
      }
    });
  });

  it("accept-all mode still passes everything (benchmark runs)", async () => {
    const handler = getHandler();
    await withMode("accept-all", async () => {
      const result = await handler(
        { toolName: "ShellSession", input: { command: "cat > main.py << 'EOF'\nx\nEOF" } },
        {},
      );
      expect(result).toBeUndefined();
    });
  });
});

describe("parseExtraPrefixes", () => {
  it("returns empty for undefined / empty / whitespace", () => {
    expect(parseExtraPrefixes(undefined)).toEqual([]);
    expect(parseExtraPrefixes("")).toEqual([]);
    expect(parseExtraPrefixes("   ")).toEqual([]);
  });
  it("splits on comma and trims leading whitespace, preserving trailing space as word boundary", () => {
    expect(parseExtraPrefixes("make , docker compose ps,  bun run")).toEqual([
      "make ",
      "docker compose ps",
      "bun run",
    ]);
  });
  it("drops empty / whitespace-only segments", () => {
    expect(parseExtraPrefixes("a,,b,")).toEqual(["a", "b"]);
    expect(parseExtraPrefixes("a,   ,b")).toEqual(["a", "b"]);
  });
});

describe("getSafePrefixes", () => {
  it("merges builtins with LITTLE_CODER_BASH_ALLOW from the env", () => {
    const prev = process.env.LITTLE_CODER_BASH_ALLOW;
    process.env.LITTLE_CODER_BASH_ALLOW = "make ,docker compose ps";
    try {
      const all = getSafePrefixes();
      expect(all).toContain("ls"); // builtin still present
      expect(all).toContain("make ");
      expect(all).toContain("docker compose ps");
    } finally {
      if (prev === undefined) delete process.env.LITTLE_CODER_BASH_ALLOW;
      else process.env.LITTLE_CODER_BASH_ALLOW = prev;
    }
  });
});
