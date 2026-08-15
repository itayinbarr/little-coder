import { describe, it, expect, beforeAll } from "vitest";
import { readFileSync, existsSync, readdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { parseSkillFile } from "./frontmatter.ts";

// Re-implement the INTENT_MAP + predict helpers here (kept in sync with
// index.ts). These are pure functions; extension integration tested via RPC.

const INTENT_MAP: Record<string, string[]> = {
  read: ["read"], show: ["read"], view: ["read"], cat: ["read"],
  write: ["write"], create: ["write", "bash"],
  implement: ["write", "read"], code: ["write", "read"],
  function: ["write", "edit"], class: ["write", "edit"],
  edit: ["edit"], change: ["edit"], modify: ["edit"],
  fix: ["edit"], update: ["edit"], replace: ["edit"],
  add: ["edit", "write"], refactor: ["edit", "read"],
  run: ["bash"], execute: ["bash"], install: ["bash"],
  build: ["bash"], test: ["bash"],
  find: ["glob", "grep"], search: ["grep"],
  grep: ["grep"], glob: ["glob"],
  fetch: ["webfetch"], download: ["webfetch"], url: ["webfetch"],
  web: ["websearch"],
};

function predictTools(userText: string): string[] {
  const words = new Set(userText.toLowerCase().split(/\s+/).filter(Boolean));
  const predicted: string[] = [];
  for (const [kw, toolNames] of Object.entries(INTENT_MAP)) {
    if (!words.has(kw)) continue;
    for (const tn of toolNames) if (!predicted.includes(tn)) predicted.push(tn);
  }
  return predicted;
}

describe("intent prediction (INTENT_MAP)", () => {
  it("predicts read for 'read config.py'", () => {
    expect(predictTools("read config.py and show me the output")).toContain("read");
    expect(predictTools("read config.py and show me the output")).toContain("read");
  });
  it("predicts edit for 'fix the bug'", () => {
    const p = predictTools("please fix the bug in auth.py");
    expect(p).toContain("edit");
  });
  it("predicts bash for 'run the tests'", () => {
    const p = predictTools("run the tests and build the project");
    expect(p).toContain("bash");
  });
  it("predicts glob+grep for 'find all files'", () => {
    const p = predictTools("find all files matching the pattern");
    expect(p).toContain("glob");
    expect(p).toContain("grep");
  });
  it("empty predictions for neutral prompts", () => {
    expect(predictTools("hello there")).toEqual([]);
  });
});

describe("skills directory loads from repo", () => {
  const here = dirname(fileURLToPath(import.meta.url));
  const toolsDir = join(here, "..", "..", "..", "skills", "tools");

  it("exists and has 15 markdown files", () => {
    expect(existsSync(toolsDir)).toBe(true);
    const files = readdirSync(toolsDir).filter((f) => f.endsWith(".md"));
    expect(files.length).toBe(15);
  });

  it("every tool skill has target_tool in frontmatter", () => {
    const files = readdirSync(toolsDir).filter((f) => f.endsWith(".md"));
    for (const file of files) {
      const parsed = parseSkillFile(readFileSync(join(toolsDir, file), "utf-8"));
      expect(parsed, `${file} should parse`).not.toBeNull();
      expect(typeof parsed!.frontmatter.target_tool).toBe("string");
    }
  });

  it("core tools are all represented", () => {
    const files = readdirSync(toolsDir).filter((f) => f.endsWith(".md"));
    const targets = new Set<string>();
    for (const file of files) {
      const parsed = parseSkillFile(readFileSync(join(toolsDir, file), "utf-8"));
      const t = parsed?.frontmatter.target_tool;
      if (typeof t === "string") targets.add(t);
    }
    for (const core of ["read", "write", "edit", "bash", "glob", "grep", "webfetch"]) {
      expect(targets.has(core), `expected target_tool=${core}`).toBe(true);
    }
  });

  it("uses target_tool names in JSON call examples", () => {
    const files = readdirSync(toolsDir).filter((f) => f.endsWith(".md"));
    for (const file of files) {
      const parsed = parseSkillFile(readFileSync(join(toolsDir, file), "utf-8"));
      const target = parsed?.frontmatter.target_tool;
      const exampleBlocks = [...(parsed?.body ?? "").matchAll(/```tool\s*\n([\s\S]*?)```/g)];
      for (const match of exampleBlocks) {
        const call = JSON.parse(match[1]);
        expect(call.name, `${file} example should use target_tool=${target}`).toBe(target);
      }
    }
  });
});
