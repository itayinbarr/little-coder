import { describe, it, expect } from "vitest";
import { stripAnsi, visibleWidth, truncateLineToWidth } from "./width.ts";

describe("stripAnsi / visibleWidth", () => {
  it("strips SGR color codes", () => {
    expect(stripAnsi("\x1b[31mred\x1b[39m")).toBe("red");
    expect(visibleWidth("\x1b[31mred\x1b[39m")).toBe(3);
  });
  it("strips OSC hyperlinks", () => {
    const link = "\x1b]8;;https://example.com\x07click\x1b]8;;\x07";
    expect(stripAnsi(link)).toBe("click");
    expect(visibleWidth(link)).toBe(5);
  });
  it("counts plain ASCII", () => {
    expect(visibleWidth("hello world")).toBe(11);
  });
});

describe("truncateLineToWidth", () => {
  it("returns the line unchanged when it fits", () => {
    expect(truncateLineToWidth("hi", 10)).toBe("hi");
  });
  it("truncates and adds an ellipsis when it overflows", () => {
    const out = truncateLineToWidth("abcdefghij", 5);
    expect(visibleWidth(out)).toBeLessThanOrEqual(5);
    expect(out).toContain("…");
  });
  it("preserves SGR codes through the visible portion", () => {
    // 12 visible chars under one color, truncate to 6
    const input = "\x1b[31m" + "abcdefghijkl" + "\x1b[39m";
    const out = truncateLineToWidth(input, 6);
    expect(out).toContain("\x1b[31m");
    // visible chars in out (after stripping ansi) should be <= 6
    expect(visibleWidth(out)).toBeLessThanOrEqual(6);
  });
  it("appends a reset to prevent color bleed after truncation", () => {
    const out = truncateLineToWidth("\x1b[31mlong red string here\x1b[39m", 8);
    expect(out.endsWith("\x1b[0m")).toBe(true);
  });
  it("handles a width of 0 defensively", () => {
    expect(truncateLineToWidth("anything", 0)).toBe("");
  });
  it("matches the issue #48 reproduction shape", () => {
    // Construct a row roughly the shape the sub-coder tracker would build,
    // with a real-world ~167-char errorMessage. Without truncation this is
    // 198 visible chars — exactly the user-reported overflow.
    const honey = (s: string) => `\x1b[38;2;225;90;31m${s}\x1b[39m`;
    const gray = (s: string) => `\x1b[90m${s}\x1b[39m`;
    const red = (s: string) => `\x1b[31m${s}\x1b[39m`;
    const longError =
      "child process exited with non-zero code 1: " +
      "Error: provider \"llamacpp\" — failed to reach " +
      "http://127.0.0.1:8888/v1/chat/completions: ECONNREFUSED (transport error 503, retries=3)";
    const row = `  ${red("✗")} deep-explorer-research  ${gray("0:47 ")}  ${gray(longError)}`;
    expect(visibleWidth(row)).toBeGreaterThan(184);
    const fixed = truncateLineToWidth(row, 184);
    expect(visibleWidth(fixed)).toBeLessThanOrEqual(184);
    expect(fixed.startsWith("  \x1b[31m✗\x1b[39m deep-explorer")).toBe(true);
    void honey; // keep import shape parity with the tracker
  });
});

describe("wide characters", () => {
  it("counts CJK and fullwidth characters as two columns", () => {
    expect(visibleWidth("中文")).toBe(4);
    expect(visibleWidth("a中b")).toBe(4);
    expect(visibleWidth("（全角）")).toBe(8);
  });
  it("counts combining marks as zero columns", () => {
    expect(visibleWidth("é")).toBe(1);
  });
  it("truncates CJK text to the column budget", () => {
    const out = truncateLineToWidth("研究报告：仓库实际位于子目录", 10);
    expect(visibleWidth(out)).toBeLessThanOrEqual(10);
    expect(stripAnsi(out).endsWith("…")).toBe(true);
  });
});
