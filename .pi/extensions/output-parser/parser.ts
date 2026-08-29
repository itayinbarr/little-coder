// Port of local/output_parser.py. Pure-function JSON repair + text-based
// tool-call extraction. Used by the output-parser extension to DETECT
// malformed tool calls (fenced, <tool_call> tags, raw JSON) in assistant
// text. Active repair (executing the extracted calls) is handled by the
// extension via session.followUp() to nudge the model back onto native
// tool-calling for subsequent turns.

export function escapeNewlinesInJsonStrings(text: string): string {
  const out: string[] = [];
  let inString = false;
  let i = 0;
  while (i < text.length) {
    const ch = text[i];
    if (ch === "\\" && inString && i + 1 < text.length) {
      out.push(ch, text[i + 1]);
      i += 2;
      continue;
    }
    if (ch === '"') {
      inString = !inString;
      out.push(ch);
    } else if (inString && ch === "\n") {
      out.push("\\n");
    } else if (inString && ch === "\t") {
      out.push("\\t");
    } else if (inString && ch === "\r") {
      out.push("\\r");
    } else {
      out.push(ch);
    }
    i++;
  }
  return out.join("");
}

/** Every brace-balanced `{…}` substring of `s`, in order, tracking nesting depth
 *  and string quoting/escapes. Nested objects are returned as part of their
 *  OUTER object, never separately, and a brace inside a string value neither
 *  opens nor closes anything. Stops at the first `{` that never closes. */
export function balancedObjects(s: string): string[] {
  const out: string[] = [];
  let i = 0;
  while (i < s.length) {
    const start = s.indexOf("{", i);
    if (start < 0) break;
    let depth = 0;
    let quote: string | null = null;
    let esc = false;
    let closed = -1;
    for (let j = start; j < s.length; j++) {
      const c = s[j];
      if (quote) {
        if (esc) esc = false;
        else if (c === "\\") esc = true;
        else if (c === quote) quote = null;
        continue;
      }
      if (c === "'" || c === '"') quote = c;
      else if (c === "{") depth++;
      else if (c === "}" && --depth === 0) { closed = j; break; }
    }
    if (closed < 0) break; // unterminated: nothing further can balance either
    out.push(s.slice(start, closed + 1));
    i = closed + 1;
  }
  return out;
}

/** The first brace-balanced `{…}` substring of `s`, or null if none closes.
 *  Unlike a `/\{[^{}]*\}/` regex it returns the OUTER object even when it nests
 *  further objects, so a valid tool call like `{"name":"Write","input":{…}}`
 *  isn't lost to its inner `input` fragment when trailing text follows it. */
export function firstBalancedObject(s: string): string | null {
  return balancedObjects(s)[0] ?? null;
}

/** The argument object of a parsed tool call, whatever the model called it.
 *  `input` is pi's own name, `parameters`/`args` are common in hand-written
 *  prompts, and `arguments` is what the OpenAI tool-call schema uses, which is
 *  the shape a model reaches for when it writes a call as text instead of
 *  emitting a native one (issue #117). OpenAI also serializes `arguments` as a
 *  JSON *string*, so a string is parsed rather than dropped. */
export function toolCallInput(data: Record<string, unknown>): Record<string, unknown> {
  const raw = data.input ?? data.parameters ?? data.arguments ?? data.args;
  if (typeof raw === "string") {
    try {
      const parsed = JSON.parse(raw);
      return parsed && typeof parsed === "object" && !Array.isArray(parsed)
        ? (parsed as Record<string, unknown>)
        : {};
    } catch {
      return {};
    }
  }
  return raw && typeof raw === "object" && !Array.isArray(raw)
    ? (raw as Record<string, unknown>)
    : {};
}

export function repairJson(raw: string): Record<string, unknown> {
  const trimmed = raw.trim();
  if (!trimmed) return {};
  // 0. direct parse
  try {
    return JSON.parse(trimmed);
  } catch {}
  // 1. re-escape literal newlines/tabs in strings
  let fixed = escapeNewlinesInJsonStrings(trimmed);
  try {
    return JSON.parse(fixed);
  } catch {}
  // 2. trailing commas
  fixed = fixed.replace(/,\s*}/g, "}").replace(/,\s*]/g, "]");
  // 3. single quotes → double, only if no doubles present
  if (!fixed.includes('"') && fixed.includes("'")) fixed = fixed.replace(/'/g, '"');
  // 4. unquoted keys — skip if content already has quoted string keys
  if (!fixed.includes('": ') && !fixed.includes('":"')) {
    fixed = fixed.replace(/(?<=[{,\s])(\w+)\s*:/g, '"$1":');
  }
  // 5. missing closing braces / brackets
  const openB = (fixed.match(/\{/g) || []).length - (fixed.match(/\}/g) || []).length;
  if (openB > 0) fixed += "}".repeat(openB);
  const openS = (fixed.match(/\[/g) || []).length - (fixed.match(/\]/g) || []).length;
  if (openS > 0) fixed += "]".repeat(openS);
  try {
    return JSON.parse(fixed);
  } catch {}
  // 6. extract the first brace-balanced object (nesting- and quote-aware, so a
  //    valid call isn't lost to an inner fragment when trailing text follows).
  const obj = firstBalancedObject(fixed);
  if (obj) {
    try {
      return JSON.parse(obj);
    } catch {}
  }
  return { _raw: raw };
}

export interface ExtractedCall {
  id: string;
  name: string;
  input: Record<string, unknown>;
  /** Which text encoding the call was recovered from. Lets the extension treat
   *  the LFM2/Liquid "Pythonic" format differently from the JSON-based ones:
   *  nudging a model back to "native" tool calls is futile when Pythonic IS its
   *  native channel, so that path informs once instead of looping. */
  format?: "fenced" | "tag" | "bare" | "liquid";
}

export function parseTextToolCalls(text: string): ExtractedCall[] {
  const calls: ExtractedCall[] = [];

  // Pattern 0: LFM2 / Liquid "Pythonic" tool calls. Checked first — the
  // <|tool_call_*|> special tokens are unambiguous and the format never
  // overlaps the JSON-based patterns below (issue #42).
  calls.push(...parseLiquidToolCalls(text));

  // Pattern 1: ```tool ... ``` or ```json ... ```
  const fenceRe = /```(?:tool|json)\s*\n([\s\S]*?)\n```/g;
  let m: RegExpExecArray | null;
  while ((m = fenceRe.exec(text))) {
    const data = repairJson(m[1]);
    if (typeof data.name === "string" && data.name) {
      calls.push({
        id: `call_text_${calls.length}`,
        name: data.name,
        input: toolCallInput(data),
        format: "fenced",
      });
    }
  }

  // Pattern 2: <tool_call> ... </tool_call>
  const tagRe = /<tool_call>\s*([\s\S]*?)\s*<\/tool_call>/g;
  while ((m = tagRe.exec(text))) {
    const data = repairJson(m[1]);
    if (typeof data.name === "string" && data.name) {
      calls.push({
        id: `call_text_${calls.length}`,
        name: data.name,
        input: toolCallInput(data),
        format: "tag",
      });
    }
  }

  // Pattern 3: a bare JSON object carrying a "name".
  //
  // This used to be `/\{[^{}]*"name"\s*:\s*"(\w+)"[^{}]*\}/g`, whose `[^{}]*`
  // excludes braces outright, so it could never match a call whose arguments
  // are themselves an object, which is the single most common way a model
  // writes one: `{"name": "read", "arguments": {"path": "foo.py"}}` (issue
  // #117). The nudge that asks the model to re-issue natively is driven off
  // this list, so a miss here is silent: nothing runs and nothing is reported.
  if (calls.length === 0) {
    for (const chunk of balancedObjects(text)) {
      if (!/"name"\s*:\s*"/.test(chunk)) continue;
      const data = repairJson(chunk);
      // A nested object is only accepted when it also carries an argument key.
      // Bare `"name"` plus arbitrary keys stays limited to FLAT objects, as
      // before: matching any `{...,"name":...,...}` in prose is how #96's false
      // positives happen, and a model discussing a config blob with a `name`
      // field must not be read as calling a tool. Requiring `name` AND one of
      // input/parameters/arguments/args is what makes the nested shape safe.
      const nested = /[{[]/.test(chunk.slice(1, -1));
      const hasArgs =
        data.input !== undefined ||
        data.parameters !== undefined ||
        data.arguments !== undefined ||
        data.args !== undefined;
      if (nested && !hasArgs) continue;
      if (typeof data.name === "string" && data.name) {
        calls.push({
          id: `call_text_${calls.length}`,
          name: data.name,
          input: toolCallInput(data),
          format: "bare",
        });
      }
    }
  }

  return calls;
}

// ── LFM2 / Liquid "Pythonic" tool-call format ───────────────────────────────
// LiquidAI LFM2 models (issue #42) emit tool calls as a Python list of function
// calls wrapped in special tokens, e.g.
//   <|tool_call_start|>[Read(path='/a.c'), Grep(pattern='x', path='.')]<|tool_call_end|>
// Argument values follow the model's chat-template `format_arg_value` macro:
//   string -> single quotes 'val' (the template does NOT escape inner quotes)
//   dict   -> JSON object {"k": "v"}
//   else   -> Python str(): 123, 1.5, True, False, None, ['a', 'b']
// Served WITHOUT llama.cpp's `--jinja`, these are never parsed into native
// tool_calls and leak into assistant TEXT — often with the start token and its
// `[` stripped and `]<|tool_call_end|><|im_end|>` trailing (the exact shape in
// the issue's error). We recover them best-effort so the harness can react with
// an accurate diagnostic instead of a cryptic parse failure.

const LIQUID_START = "<|tool_call_start|>";
const LIQUID_END = "<|tool_call_end|>";

/** Split `s` on a single-char separator, ignoring separators inside quotes
 *  (single or double, with `\` escaping) or inside (), [], {} of any depth. */
function splitTopLevel(s: string, sep: string): string[] {
  const parts: string[] = [];
  let depth = 0;
  let quote: string | null = null;
  let esc = false;
  let cur = "";
  for (const c of s) {
    cur += c;
    if (quote) {
      if (esc) esc = false;
      else if (c === "\\") esc = true;
      else if (c === quote) quote = null;
      continue;
    }
    if (c === "'" || c === '"') quote = c;
    else if (c === "(" || c === "[" || c === "{") depth++;
    else if (c === ")" || c === "]" || c === "}") depth--;
    else if (c === sep && depth === 0) {
      parts.push(cur.slice(0, -1));
      cur = "";
    }
  }
  parts.push(cur);
  return parts;
}

/** Index of the first top-level occurrence of `ch` (quote/bracket-aware), or -1. */
function topLevelIndexOf(s: string, ch: string): number {
  let depth = 0;
  let quote: string | null = null;
  let esc = false;
  for (let i = 0; i < s.length; i++) {
    const c = s[i];
    if (quote) {
      if (esc) esc = false;
      else if (c === "\\") esc = true;
      else if (c === quote) quote = null;
      continue;
    }
    if (c === "'" || c === '"') quote = c;
    else if (c === "(" || c === "[" || c === "{") depth++;
    else if (c === ")" || c === "]" || c === "}") depth--;
    else if (c === ch && depth === 0) return i;
  }
  return -1;
}

function unescapePy(s: string): string {
  return s.replace(/\\(['"\\nrt])/g, (_, c) => (c === "n" ? "\n" : c === "t" ? "\t" : c === "r" ? "\r" : c));
}

/** Coerce one Python-literal argument value (as rendered by `format_arg_value`)
 *  into a JS value. Best-effort and total — never throws; an unrecognized token
 *  falls through as a bare string so no data is lost. Returns undefined only for
 *  an empty slot (e.g. a trailing comma). */
function parsePyValue(raw: string): unknown {
  const s = raw.trim();
  if (!s) return undefined;
  const c0 = s[0];
  // String — strip the outer matching quote. Slicing first/last (rather than
  // unescaping a closing quote) tolerates the template's unescaped inner quotes
  // for the common case where the value still begins and ends with the quote.
  if (c0 === "'" || c0 === '"') {
    const inner = s[s.length - 1] === c0 && s.length >= 2 ? s.slice(1, -1) : s.slice(1);
    return unescapePy(inner);
  }
  if (c0 === "{") {
    const obj = repairJson(s);
    return "_raw" in obj && Object.keys(obj).length === 1 ? s : obj;
  }
  if (c0 === "[") return parsePyList(s);
  if (s === "True" || s.toLowerCase() === "true") return true;
  if (s === "False" || s.toLowerCase() === "false") return false;
  if (s === "None" || s.toLowerCase() === "null" || s.toLowerCase() === "none") return null;
  if (/^[+-]?(\d+\.?\d*|\.\d+)([eE][+-]?\d+)?$/.test(s)) return Number(s);
  return s; // bareword / unquoted — keep verbatim
}

function parsePyList(s: string): unknown[] {
  const inner = s.trim().replace(/^\[/, "").replace(/\]$/, "");
  if (!inner.trim()) return [];
  return splitTopLevel(inner, ",")
    .map(parsePyValue)
    .filter((v) => v !== undefined);
}

/** Parse a `name(arg=val, ...)` Python call. Tolerates a truncated tail (a
 *  missing closing paren). Returns null when there's no `name(` head. */
function parsePyCall(raw: string): { name: string; input: Record<string, unknown> } | null {
  const s = raw.trim();
  const open = s.indexOf("(");
  if (open < 0) return null;
  const name = s.slice(0, open).trim();
  if (!/^[A-Za-z_]\w*$/.test(name)) return null;
  // Find the matching close paren (quote/bracket-aware); fall back to end on truncation.
  let depth = 0;
  let quote: string | null = null;
  let esc = false;
  let end = -1;
  for (let i = open; i < s.length; i++) {
    const c = s[i];
    if (quote) {
      if (esc) esc = false;
      else if (c === "\\") esc = true;
      else if (c === quote) quote = null;
      continue;
    }
    if (c === "'" || c === '"') quote = c;
    else if (c === "(") depth++;
    else if (c === ")") {
      depth--;
      if (depth === 0) {
        end = i;
        break;
      }
    }
  }
  const argsBlob = end >= 0 ? s.slice(open + 1, end) : s.slice(open + 1);
  const input: Record<string, unknown> = {};
  for (const part of splitTopLevel(argsBlob, ",")) {
    const seg = part.trim();
    if (!seg) continue;
    const eq = topLevelIndexOf(seg, "=");
    if (eq < 0) continue; // positional/garbage — LFM2 always emits kwargs; skip safely
    const key = seg.slice(0, eq).trim();
    if (!/^[A-Za-z_]\w*$/.test(key)) continue;
    const val = parsePyValue(seg.slice(eq + 1));
    if (val !== undefined) input[key] = val;
  }
  return { name, input };
}

/** Recover LFM2/Liquid Pythonic tool calls from assistant text. High-precision:
 *  fires on the `<|tool_call_*|>` special tokens, or — without them — only when
 *  the whole message is a `[...]` bracket list, since every element must still
 *  parse as a `name(...)` call. */
export function parseLiquidToolCalls(text: string): ExtractedCall[] {
  const hasStart = text.includes(LIQUID_START);
  const hasEnd = text.includes(LIQUID_END);
  let region: string;
  if (hasStart || hasEnd) {
    let s = text;
    if (hasStart) s = s.slice(s.indexOf(LIQUID_START) + LIQUID_START.length);
    if (s.includes(LIQUID_END)) s = s.slice(0, s.indexOf(LIQUID_END));
    region = s;
  } else {
    // No special tokens (some llama.cpp builds/templates emit the bare list).
    // Reasoning LFM2 models put the call list AFTER a <think>…</think> block —
    // e.g. `</think>[Read(path="/a"), Bash(command="ls")]` (verified against
    // LFM2.5-8B-A1B). Strip a leading think block, then require the remainder to
    // be exactly a `[…]` list so prose can't trip it.
    const t = text.trim().replace(/^<think>[\s\S]*?<\/think>\s*/, "").trim();
    if (!(t.startsWith("[") && t.endsWith("]"))) return [];
    region = t;
  }
  // Drop any leftover special tokens, then one wrapping [ ... ] of the call list.
  region = region.replace(/<\|tool_call_(?:start|end)\|>/g, "").replace(/<\|im_end\|>/g, "").trim();
  if (region.startsWith("[")) region = region.slice(1);
  if (region.endsWith("]")) region = region.slice(0, -1);
  region = region.trim();
  if (!region) return [];

  const calls: ExtractedCall[] = [];
  for (const part of splitTopLevel(region, ",")) {
    const call = parsePyCall(part);
    if (call) calls.push({ id: `call_text_${calls.length}`, name: call.name, input: call.input, format: "liquid" });
  }
  return calls;
}
