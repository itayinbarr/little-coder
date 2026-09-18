import { describe, it, expect } from "vitest";
import { mkdtempSync, mkdirSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { findSkillsRoot, skillPackDir } from "./skills-root.ts";

describe("skills root resolution (PR #62)", () => {
  it("finds it from the little-coder checkout layout", () => {
    // .pi/extensions/<name>/ → three levels up.
    const root = mkdtempSync(join(tmpdir(), "lc-skills-"));
    try {
      mkdirSync(join(root, "skills", "tools"), { recursive: true });
      const ext = join(root, ".pi", "extensions", "skill-inject");
      mkdirSync(ext, { recursive: true });
      expect(findSkillsRoot(ext)).toBe(join(root, "skills"));
      expect(skillPackDir(ext, "tools")).toBe(join(root, "skills", "tools"));
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("finds it from the built pi-package layout, where the old path count was wrong", () => {
    // extensions/<name>/ → TWO levels up. The hardcoded three-level join
    // resolved above the package root, existsSync returned false, and both
    // loaders returned early with no skills and no error.
    const root = mkdtempSync(join(tmpdir(), "lc-skills-"));
    try {
      mkdirSync(join(root, "skills", "knowledge"), { recursive: true });
      const ext = join(root, "extensions", "knowledge-inject");
      mkdirSync(ext, { recursive: true });
      expect(findSkillsRoot(ext)).toBe(join(root, "skills"));
      expect(skillPackDir(ext, "knowledge")).toBe(join(root, "skills", "knowledge"));
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("returns undefined when there is no skills directory anywhere above", () => {
    const root = mkdtempSync(join(tmpdir(), "lc-skills-"));
    try {
      expect(findSkillsRoot(root, () => false)).toBeUndefined();
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("returns undefined for a pack the root does not carry", () => {
    const root = mkdtempSync(join(tmpdir(), "lc-skills-"));
    try {
      mkdirSync(join(root, "skills", "tools"), { recursive: true });
      expect(skillPackDir(root, "protocols")).toBeUndefined();
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("takes the NEAREST skills root, not one further up", () => {
    const root = mkdtempSync(join(tmpdir(), "lc-skills-"));
    try {
      mkdirSync(join(root, "skills", "tools"), { recursive: true });
      const inner = join(root, "node_modules", "pi-little-coder");
      mkdirSync(join(inner, "skills", "tools"), { recursive: true });
      const ext = join(inner, "extensions", "skill-inject");
      mkdirSync(ext, { recursive: true });
      expect(findSkillsRoot(ext)).toBe(join(inner, "skills"));
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});
