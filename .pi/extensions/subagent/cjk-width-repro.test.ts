import { describe, it, expect } from "vitest";
import { makeComponent } from "./index.ts";

// Independent of the code under test: CJK ideographs, CJK punctuation and
// fullwidth forms take two terminal columns, everything used here takes one.
const columns = (s: string) =>
  [...s.replace(/\x1b\[[0-9;]*[a-zA-Z]/g, "")].reduce(
    (w, ch) => w + (/[\u3000-\u303f\u4e00-\u9fff\uff00-\uff60]/.test(ch) ? 2 : 1),
    0,
  );

// Regression for a crash with CJK sub-coder reports: the wrap measured
// String.length, so a Chinese sentence fitting in 241 chars rendered
// 245 columns wide at terminal width 243 and pi-tui aborted the session
// ("Rendered line 147 exceeds terminal width (245 > 243)").

const report =
  "**直接回答**：skill 成功获取。`github.com/pans0020/research-writing` 为 404，实际仓库是 **Pans0020/opencode-skills** 的 `research-writing/` 目录（含 4 个文件：SKILL.md 24.1KB、DEPLOY.md、QUICKSTART.md、README.md）。agentskill.sh 可正常访问。";

describe("CJK sub-coder report fits the pi-supplied width", () => {
  for (const width of [243, 120, 80, 40]) {
    it(`wraps to width ${width}`, () => {
      const out = makeComponent(["✓ pans0020-research-writing", report, "  …"]).render(width);
      for (const line of out) expect(columns(line)).toBeLessThanOrEqual(width - 1);
      // No text is lost: every CJK char of the report is still present.
      const joined = out.join("");
      for (const ch of "直接回答成功获取实际仓库是目录可正常访问") expect(joined).toContain(ch);
    });
  }

  it("wraps a long CJK run with no spaces", () => {
    const out = makeComponent(["中".repeat(300)]).render(81);
    expect(out.length).toBeGreaterThan(1);
    for (const line of out) expect(columns(line)).toBeLessThanOrEqual(80);
  });
});
