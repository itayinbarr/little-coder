// Width-aware truncation for custom TUI widget content.
//
// pi-tui (>= ~0.75) throws "Rendered line N exceeds terminal width" when any
// rendered line is wider than the terminal — see issue #48. Custom widgets
// (subagent tracker, plan-mode status/indicator, branding header) MUST cap
// every line they emit to the active terminal width, or pi crashes the whole
// session when the widget happens to produce a long line (e.g. a failed
// sub-coder whose errorMessage runs ~200 chars).
//
// pi-tui itself exports visibleWidth + truncateToWidth, but pi 0.79 no longer
// hoists pi-tui to the top-level node_modules, so extensions can't import it
// directly. This module is the lightweight inline replacement: it strips
// SGR / OSC escapes for the width count and walks the string char-by-char to
// truncate while preserving any in-flight color codes.

const SGR_RE = /\x1b\[[0-9;]*[a-zA-Z]/g;
const OSC_RE = /\x1b\][^\x07]*\x07/g;

export function stripAnsi(s: string): string {
  return s.replace(SGR_RE, "").replace(OSC_RE, "");
}

// Terminal column width of one code point: 0 for combining marks and
// zero-width characters, 2 for East Asian Wide/Fullwidth characters and
// emoji, 1 otherwise. Mirrors wcwidth closely enough for pi-tui's
// line-width check; CJK text counted as 1 column per char overflowed the
// terminal and crashed pi.
export function charWidth(ch: string): number {
  const cp = ch.codePointAt(0) ?? 0;
  if (cp === 0 || cp < 0x20 || (cp >= 0x7f && cp < 0xa0)) return 0;
  if (
    (cp >= 0x0300 && cp <= 0x036f) || // combining diacritics
    (cp >= 0x200b && cp <= 0x200f) || // zero-width space/joiners, marks
    (cp >= 0xfe00 && cp <= 0xfe0f) || // variation selectors
    (cp >= 0xe0100 && cp <= 0xe01ef)
  ) {
    return 0;
  }
  if (
    (cp >= 0x1100 && cp <= 0x115f) || // Hangul Jamo
    (cp >= 0x2e80 && cp <= 0x303e) || // CJK radicals, punctuation
    (cp >= 0x3041 && cp <= 0x33ff) || // kana, CJK symbols
    (cp >= 0x3400 && cp <= 0x4dbf) || // CJK Ext A
    (cp >= 0x4e00 && cp <= 0x9fff) || // CJK Unified
    (cp >= 0xa000 && cp <= 0xa4cf) || // Yi
    (cp >= 0xac00 && cp <= 0xd7a3) || // Hangul syllables
    (cp >= 0xf900 && cp <= 0xfaff) || // CJK compatibility
    (cp >= 0xfe30 && cp <= 0xfe4f) || // CJK compatibility forms
    (cp >= 0xff00 && cp <= 0xff60) || // fullwidth forms
    (cp >= 0xffe0 && cp <= 0xffe6) ||
    (cp >= 0x1f300 && cp <= 0x1f64f) || // emoji
    (cp >= 0x1f900 && cp <= 0x1f9ff) ||
    (cp >= 0x20000 && cp <= 0x3fffd) // CJK Ext B+
  ) {
    return 2;
  }
  return 1;
}

// Display width of an ANSI-stripped string, in terminal columns.
export function visibleWidth(s: string): number {
  let w = 0;
  for (const ch of stripAnsi(s)) w += charWidth(ch);
  return w;
}

// Truncate `line` so its visible width fits `maxWidth`. ANSI escapes are
// preserved verbatim; the visible portion is cut at maxWidth-1 to leave room
// for an ellipsis, and a final SGR reset is appended so a half-emitted color
// can't bleed into the next line. If maxWidth ≤ 0, returns "" (defensive).
export function truncateLineToWidth(line: string, maxWidth: number, ellipsis = "…"): string {
  if (maxWidth <= 0) return "";
  if (visibleWidth(line) <= maxWidth) return line;
  const cutAt = Math.max(0, maxWidth - visibleWidth(ellipsis));
  let visible = 0;
  let out = "";
  let i = 0;
  while (i < line.length) {
    const ch = line[i];
    if (ch === "\x1b" && line[i + 1] === "[") {
      const m = line.slice(i).match(/^\x1b\[[0-9;]*[a-zA-Z]/);
      if (m) {
        out += m[0];
        i += m[0].length;
        continue;
      }
    }
    if (ch === "\x1b" && line[i + 1] === "]") {
      const end = line.indexOf("\x07", i);
      if (end >= 0) {
        out += line.slice(i, end + 1);
        i = end + 1;
        continue;
      }
    }
    const cp = line.codePointAt(i) ?? 0;
    const glyph = String.fromCodePoint(cp);
    const w = charWidth(glyph);
    if (visible + w > cutAt) break;
    out += glyph;
    visible += w;
    i += glyph.length;
  }
  return out + ellipsis + "\x1b[0m";
}

// Current terminal width, with a small safety margin for glyphs whose
// rendered width differs from charWidth's table (ambiguous-width symbols,
// newer emoji). Falls back to `fallback` columns when stdout isn't a TTY.
const SAFETY_MARGIN = 2;
export function terminalColumns(fallback = 80): number {
  const c = (process.stdout && (process.stdout as any).columns) | 0;
  const w = c > 0 ? c : fallback;
  return Math.max(20, w - SAFETY_MARGIN);
}
