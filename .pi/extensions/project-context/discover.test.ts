import { describe, it, expect } from "vitest";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  CONTEXT_FILENAMES,
  DEFAULT_MAX_CHARS,
  capContent,
  findContextFile,
  formatProjectContext,
  isEnabled,
  loadProjectContext,
  maxChars,
} from "./discover.ts";

function tmp(): string {
  return mkdtempSync(join(tmpdir(), "lc-projctx-"));
}

describe("project context discovery (issue #104)", () => {
  it("finds AGENTS.md in the launch directory", () => {
    const dir = tmp();
    try {
      writeFileSync(join(dir, "AGENTS.md"), "rules");
      expect(findContextFile(dir)).toBe(join(dir, "AGENTS.md"));
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("walks UP to the repo root, since running from a subdirectory is normal", () => {
    const dir = tmp();
    try {
      writeFileSync(join(dir, "AGENTS.md"), "rules");
      const deep = join(dir, "src", "api", "handlers");
      mkdirSync(deep, { recursive: true });
      expect(findContextFile(deep)).toBe(join(dir, "AGENTS.md"));
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("accepts CLAUDE.md when there is no AGENTS.md", () => {
    const dir = tmp();
    try {
      writeFileSync(join(dir, "CLAUDE.md"), "rules");
      expect(findContextFile(dir)).toBe(join(dir, "CLAUDE.md"));
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("prefers AGENTS.md over CLAUDE.md at the same level", () => {
    const dir = tmp();
    try {
      writeFileSync(join(dir, "AGENTS.md"), "a");
      writeFileSync(join(dir, "CLAUDE.md"), "c");
      expect(findContextFile(dir)).toBe(join(dir, "AGENTS.md"));
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("takes the NEAREST file, not the outermost", () => {
    const dir = tmp();
    try {
      writeFileSync(join(dir, "AGENTS.md"), "outer");
      const inner = join(dir, "packages", "web");
      mkdirSync(inner, { recursive: true });
      writeFileSync(join(inner, "AGENTS.md"), "inner");
      expect(findContextFile(inner)).toBe(join(inner, "AGENTS.md"));
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("never loads little-coder's own AGENTS.md (it IS the system prompt)", () => {
    // Running little-coder inside its own checkout would otherwise append a
    // second copy of the prompt the session is already running on.
    const dir = tmp();
    try {
      const own = join(dir, "AGENTS.md");
      writeFileSync(own, "little-coder's own harness prompt");
      expect(findContextFile(dir, [own])).toBeUndefined();
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("skipping the package's own file still finds a real project file above it", () => {
    const dir = tmp();
    try {
      writeFileSync(join(dir, "AGENTS.md"), "the user's project rules");
      const nested = join(dir, "vendored-little-coder");
      mkdirSync(nested, { recursive: true });
      const own = join(nested, "AGENTS.md");
      writeFileSync(own, "harness prompt");
      expect(findContextFile(nested, [own])).toBe(join(dir, "AGENTS.md"));
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("returns undefined when nothing is found anywhere up the tree", () => {
    const dir = tmp();
    try {
      // No file written; the walk reaches the filesystem root and stops.
      expect(findContextFile(dir, [], () => false)).toBeUndefined();
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("searches exactly the documented filenames", () => {
    expect([...CONTEXT_FILENAMES]).toEqual(["AGENTS.md", "CLAUDE.md"]);
  });
});

describe("the cold-start budget cap", () => {
  it("leaves a file that fits completely alone", () => {
    expect(capContent("short", 4000)).toEqual({ content: "short", truncatedChars: 0 });
  });

  it("cuts at a line break so the model is never handed half a rule", () => {
    const body = "line one\nline two\nline three that runs past the budget";
    const { content, truncatedChars } = capContent(body, 20);
    expect(content).toBe("line one\nline two");
    expect(truncatedChars).toBe(body.length - content.length);
  });

  it("falls back to a hard cut when there is no usable line break", () => {
    const body = "x".repeat(100);
    const { content, truncatedChars } = capContent(body, 10);
    expect(content).toHaveLength(10);
    expect(truncatedChars).toBe(90);
  });

  it("maxChars: 0 means no cap, for someone who owns their own budget", () => {
    expect(maxChars({ LITTLE_CODER_PROJECT_CONTEXT_MAX_CHARS: "0" })).toBe(Number.MAX_SAFE_INTEGER);
  });

  it("maxChars: garbage falls back to the default rather than to zero", () => {
    expect(maxChars({ LITTLE_CODER_PROJECT_CONTEXT_MAX_CHARS: "banana" })).toBe(DEFAULT_MAX_CHARS);
    expect(maxChars({ LITTLE_CODER_PROJECT_CONTEXT_MAX_CHARS: "-5" })).toBe(DEFAULT_MAX_CHARS);
    expect(maxChars({})).toBe(DEFAULT_MAX_CHARS);
  });
});

describe("loadProjectContext", () => {
  it("reads, trims and caps in one step", () => {
    const dir = tmp();
    try {
      writeFileSync(join(dir, "AGENTS.md"), "\n\n  use bun, not npm  \n\n");
      const found = loadProjectContext(dir);
      expect(found?.content).toBe("use bun, not npm");
      expect(found?.truncatedChars).toBe(0);
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("ignores an empty file rather than injecting an empty block", () => {
    const dir = tmp();
    try {
      writeFileSync(join(dir, "AGENTS.md"), "   \n  \n");
      expect(loadProjectContext(dir)).toBeUndefined();
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("ignores a DIRECTORY named AGENTS.md instead of trying to read it", () => {
    const dir = tmp();
    try {
      mkdirSync(join(dir, "AGENTS.md"));
      expect(loadProjectContext(dir)).toBeUndefined();
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });

  it("reports truncation so a cut-off rule is never debugged blind", () => {
    const dir = tmp();
    try {
      writeFileSync(join(dir, "AGENTS.md"), "a".repeat(9000));
      const found = loadProjectContext(dir)!;
      expect(found.content.length).toBe(DEFAULT_MAX_CHARS);
      expect(found.truncatedChars).toBe(9000 - DEFAULT_MAX_CHARS);
      expect(formatProjectContext(found)).toContain("truncated: 5000 more characters");
    } finally {
      rmSync(dir, { recursive: true, force: true });
    }
  });
});

describe("the injected block", () => {
  const found = { path: "/repo/AGENTS.md", content: "use bun", truncatedChars: 0 };

  it("names the file, so the model does not read it as the user talking", () => {
    const block = formatProjectContext(found);
    expect(block).toContain('<project_instructions source="/repo/AGENTS.md">');
    expect(block).toContain("use bun");
    expect(block).toContain("</project_instructions>");
  });

  it("states the precedence explicitly rather than leaving it to be inferred", () => {
    // A project file saying "always run the full suite" against a harness rule
    // is exactly the conflict a small model resolves badly.
    expect(formatProjectContext(found)).toContain("your operating instructions win");
  });

  it("says nothing about truncation when nothing was truncated", () => {
    expect(formatProjectContext(found)).not.toContain("truncated");
  });
});

describe("the opt-out", () => {
  it("is on by default", () => {
    expect(isEnabled({})).toBe(true);
  });

  it("accepts the three spellings people actually type", () => {
    expect(isEnabled({ LITTLE_CODER_PROJECT_CONTEXT: "0" })).toBe(false);
    expect(isEnabled({ LITTLE_CODER_PROJECT_CONTEXT: "off" })).toBe(false);
    expect(isEnabled({ LITTLE_CODER_PROJECT_CONTEXT: "false" })).toBe(false);
  });

  it("anything else leaves it on", () => {
    expect(isEnabled({ LITTLE_CODER_PROJECT_CONTEXT: "1" })).toBe(true);
  });
});
