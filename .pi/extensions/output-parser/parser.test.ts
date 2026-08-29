import { describe, it, expect } from "vitest";
import { repairJson, parseTextToolCalls, parseLiquidToolCalls, escapeNewlinesInJsonStrings, firstBalancedObject } from "./parser.ts";

describe("firstBalancedObject", () => {
  it("returns the OUTER object even when it nests further objects", () => {
    const s = '{"name":"Write","input":{"a":1}}';
    expect(firstBalancedObject(s)).toBe(s);
  });
  it("ignores braces that live inside string values", () => {
    expect(firstBalancedObject('{"a":"}"}')).toBe('{"a":"}"}');
  });
  it("stops at the first fully balanced object", () => {
    expect(firstBalancedObject('{"a":1} {"b":2}')).toBe('{"a":1}');
  });
  it("returns null when nothing balances", () => {
    expect(firstBalancedObject("{unterminated")).toBeNull();
    expect(firstBalancedObject("no braces here")).toBeNull();
  });
});

describe("repairJson recovers a nested call before trailing garbage (LOGIC-001)", () => {
  it("keeps the outer call, not the inner input fragment, when text follows it", () => {
    const out = repairJson('{"name":"Write","input":{"path":"/a"}}\nSorry, retry: {broken');
    expect(out.name).toBe("Write");
    expect(out.input).toEqual({ path: "/a" });
  });
  it("parses a whole tool call whose string value contains a brace", () => {
    const out = repairJson('{"name":"Bash","input":{"command":"echo {"}} and then junk');
    expect(out.name).toBe("Bash");
    expect((out.input as Record<string, unknown>).command).toBe("echo {");
  });
});

describe("repairJson", () => {
  it("direct parse on valid JSON", () => {
    expect(repairJson('{"a":1}')).toEqual({ a: 1 });
  });
  it("trailing commas", () => {
    expect(repairJson('{"a":1,}')).toEqual({ a: 1 });
    expect(repairJson('[1,2,]')).toEqual([1, 2]);
  });
  it("single quotes", () => {
    expect(repairJson("{'a':1}")).toEqual({ a: 1 });
  });
  it("unquoted keys", () => {
    expect(repairJson("{a:1}")).toEqual({ a: 1 });
  });
  it("missing closing brace", () => {
    expect(repairJson('{"a":1')).toEqual({ a: 1 });
  });
  it("literal newlines in strings", () => {
    const input = '{"text":"line1\nline2"}';
    expect(repairJson(input)).toEqual({ text: "line1\nline2" });
  });
  it("escapeNewlinesInJsonStrings leaves non-string content alone", () => {
    expect(escapeNewlinesInJsonStrings('{"a":1,\n"b":2}')).toBe('{"a":1,\n"b":2}');
  });
  it("truncated / garbage returns _raw sentinel", () => {
    const result = repairJson("not json at all");
    expect(result._raw).toBe("not json at all");
  });
});

describe("parseTextToolCalls", () => {
  it("extracts fenced ```tool block", () => {
    const text = 'reasoning first\n```tool\n{"name":"Read","input":{"file_path":"/x.py"}}\n```';
    const calls = parseTextToolCalls(text);
    expect(calls.length).toBe(1);
    expect(calls[0].name).toBe("Read");
    expect(calls[0].input).toEqual({ file_path: "/x.py" });
  });
  it("extracts ```json block (Gemma pattern)", () => {
    const text = '```json\n{"name":"Bash","input":{"command":"ls"}}\n```';
    const calls = parseTextToolCalls(text);
    expect(calls[0].name).toBe("Bash");
  });
  it("extracts <tool_call> tag", () => {
    const text = '<tool_call>\n{"name":"Edit","input":{"file_path":"/a","old_string":"x","new_string":"y"}}\n</tool_call>';
    const calls = parseTextToolCalls(text);
    expect(calls[0].name).toBe("Edit");
    expect(calls[0].input).toHaveProperty("new_string", "y");
  });
  it("extracts multiple fenced calls", () => {
    const text =
      '```tool\n{"name":"Read","input":{"file_path":"/a"}}\n```\n' +
      'later\n```tool\n{"name":"Read","input":{"file_path":"/b"}}\n```';
    const calls = parseTextToolCalls(text);
    expect(calls.length).toBe(2);
    expect(calls[0].input.file_path).toBe("/a");
    expect(calls[1].input.file_path).toBe("/b");
  });
  it("falls back to bare JSON for flat objects (no nested input)", () => {
    // The bare-JSON regex is restricted to flat objects ([^{}]*), matching
    // the Python implementation. A nested "input": {...} won't match; the
    // model must use a fenced block for those.
    const text = 'the model said: {"name":"Glob","pattern":"**/*.py"}';
    const calls = parseTextToolCalls(text);
    expect(calls.length).toBe(1);
    expect(calls[0].name).toBe("Glob");
  });
  it("#117: extracts a bare call whose arguments are a nested object", () => {
    // The old flat regex `\{[^{}]*"name"...[^{}]*\}` excluded braces, so it
    // could not match the shape a model actually writes. The call was not
    // recognised as an attempted call at all, so the "re-issue this natively"
    // nudge never fired and the run ended having executed nothing.
    for (const key of ["input", "parameters", "arguments", "args"]) {
      const text = `the model said: {"name":"Glob","${key}":{"pattern":"**/*.py"}}`;
      const calls = parseTextToolCalls(text);
      expect(calls.length, key).toBe(1);
      expect(calls[0].name).toBe("Glob");
      expect(calls[0].input).toEqual({ pattern: "**/*.py" });
    }
  });

  it("#117: reads an OpenAI-style arguments string", () => {
    const text = 'text {"name":"read","arguments":"{\\"path\\": \\"/a.py\\"}"}';
    const calls = parseTextToolCalls(text);
    expect(calls.length).toBe(1);
    expect(calls[0].input).toEqual({ path: "/a.py" });
  });

  it("#117/#96: a nested object with no argument key is NOT a tool call", () => {
    // Guards the false-positive direction: prose containing JSON that merely
    // has a `name` field must not be read as a call just because balanced
    // matching can now see it.
    const text = 'the config looks like {"name":"my-app","scripts":{"build":"tsc"}}';
    expect(parseTextToolCalls(text)).toEqual([]);
  });
  it("repairs trailing comma inside fenced block", () => {
    const text = '```tool\n{"name":"Read","input":{"file_path":"/x"},}\n```';
    const calls = parseTextToolCalls(text);
    expect(calls[0].name).toBe("Read");
  });
  it("accepts parameters/args alias for input", () => {
    const text = '```tool\n{"name":"Read","parameters":{"file_path":"/x"}}\n```';
    const calls = parseTextToolCalls(text);
    expect(calls[0].input.file_path).toBe("/x");
  });
  it("empty on plain text", () => {
    expect(parseTextToolCalls("just regular text, no tools here")).toEqual([]);
  });

  it("extracts an LFM2/Liquid Pythonic call via parseTextToolCalls and tags format", () => {
    const text = "<|tool_call_start|>[Read(path='/a.c')]<|tool_call_end|>";
    const calls = parseTextToolCalls(text);
    expect(calls.length).toBe(1);
    expect(calls[0].name).toBe("Read");
    expect(calls[0].input).toEqual({ path: "/a.c" });
    expect(calls[0].format).toBe("liquid");
  });
});

describe("parseLiquidToolCalls (LFM2 / Liquid Pythonic format)", () => {
  it("canonical single call wrapped in special tokens", () => {
    const calls = parseLiquidToolCalls("<|tool_call_start|>[Read(path='/home/user/foo.c')]<|tool_call_end|>");
    expect(calls).toEqual([{ id: "call_text_0", name: "Read", input: { path: "/home/user/foo.c" }, format: "liquid" }]);
  });

  it("recovers the exact issue #42 leak shape (start token + [ stripped, end + im_end trailing)", () => {
    // From the issue: `Failed to parse input at pos 57: Read(path='/home/user/foo.c')]<|tool_call_end|><|im_end|>`
    const text = "Read(path='/home/user/foo.c')]<|tool_call_end|><|im_end|>";
    const calls = parseLiquidToolCalls(text);
    expect(calls.length).toBe(1);
    expect(calls[0].name).toBe("Read");
    expect(calls[0].input).toEqual({ path: "/home/user/foo.c" });
  });

  it("multiple calls in one list", () => {
    const text = "<|tool_call_start|>[Read(path='/a'), Bash(command='ls -la')]<|tool_call_end|>";
    const calls = parseLiquidToolCalls(text);
    expect(calls.map((c) => c.name)).toEqual(["Read", "Bash"]);
    expect(calls[1].input).toEqual({ command: "ls -la" });
  });

  it("commas and parens INSIDE a string value don't split args/calls", () => {
    const text = "<|tool_call_start|>[Bash(command='echo (hi), then ls')]<|tool_call_end|>";
    const calls = parseLiquidToolCalls(text);
    expect(calls.length).toBe(1);
    expect(calls[0].input).toEqual({ command: "echo (hi), then ls" });
  });

  it("double-quoted string values (model variant)", () => {
    const calls = parseLiquidToolCalls('<|tool_call_start|>[Read(path="/a.c")]<|tool_call_end|>');
    expect(calls[0].input).toEqual({ path: "/a.c" });
  });

  it("Python scalar types: int, float, True/False, None", () => {
    const text =
      "<|tool_call_start|>[Conf(n=3, ratio=1.5, neg=-2, flag=True, off=False, none=None)]<|tool_call_end|>";
    const calls = parseLiquidToolCalls(text);
    expect(calls[0].input).toEqual({ n: 3, ratio: 1.5, neg: -2, flag: true, off: false, none: null });
  });

  it("list arg (Python repr, single quotes, internal commas)", () => {
    const text = "<|tool_call_start|>[Grep(paths=['a.py', 'b.py'], pattern='x')]<|tool_call_end|>";
    const calls = parseLiquidToolCalls(text);
    expect(calls[0].input).toEqual({ paths: ["a.py", "b.py"], pattern: "x" });
  });

  it("dict arg rendered as JSON (tojson)", () => {
    const text = '<|tool_call_start|>[Run(opts={"x": 1, "y": "z"})]<|tool_call_end|>';
    const calls = parseLiquidToolCalls(text);
    expect(calls[0].input).toEqual({ opts: { x: 1, y: "z" } });
  });

  it("no-arg call", () => {
    const calls = parseLiquidToolCalls("<|tool_call_start|>[ListDir()]<|tool_call_end|>");
    expect(calls).toEqual([{ id: "call_text_0", name: "ListDir", input: {}, format: "liquid" }]);
  });

  it("truncated tail: missing closing paren / bracket / quote", () => {
    const text = "<|tool_call_start|>[Read(path='/home/user/foo.c";
    const calls = parseLiquidToolCalls(text);
    expect(calls.length).toBe(1);
    expect(calls[0].name).toBe("Read");
    expect(calls[0].input).toEqual({ path: "/home/user/foo.c" });
  });

  it("bare whole-message bracket list (no special tokens)", () => {
    const calls = parseLiquidToolCalls("[Read(path='/a'), Read(path='/b')]");
    expect(calls.map((c) => c.input.path)).toEqual(["/a", "/b"]);
  });

  it("recovers REAL LFM2.5-8B-A1B output: <think>…</think> then a bare, double-quoted call list", () => {
    // Captured verbatim from llama.cpp serving LiquidAI/LFM2.5-8B-A1B-Q4_K_M:
    // the model reasons in <think>…</think>, emits NO special tokens, and uses
    // DOUBLE quotes — none of which the first cut of this parser handled.
    const real =
      '<think>\nOkay, the user wants two things. First read the file, then run the ls command.\n' +
      'For Read the parameter is "path"; for Bash the command is "ls -la /tmp".\n</think>' +
      '[Read(path="/home/user/foo.c"), Bash(command="ls -la /tmp")]';
    const calls = parseLiquidToolCalls(real);
    expect(calls.map((c) => c.name)).toEqual(["Read", "Bash"]);
    expect(calls[0].input).toEqual({ path: "/home/user/foo.c" });
    expect(calls[1].input).toEqual({ command: "ls -la /tmp" });
  });

  it("does not fire while the model is still inside an unclosed <think> block", () => {
    expect(parseLiquidToolCalls("<think>\nI should call [Read(path='/a')] next...")).toEqual([]);
  });

  it("preserves spaces inside string values, trims around args", () => {
    const calls = parseLiquidToolCalls("<|tool_call_start|>[Bash(  command = 'git status'  )]<|tool_call_end|>");
    expect(calls[0].input).toEqual({ command: "git status" });
  });

  // ── precision: must NOT fire on ordinary prose ──────────────────────────────
  it("ignores plain prose", () => {
    expect(parseLiquidToolCalls("I'll read the file and report back.")).toEqual([]);
  });

  it("ignores a markdown/JSON array that isn't a call list", () => {
    expect(parseLiquidToolCalls("[1, 2, 3]")).toEqual([]);
    expect(parseLiquidToolCalls('["a", "b"]')).toEqual([]);
  });

  it("ignores a bracketed phrase in prose that isn't a clean call list", () => {
    expect(parseLiquidToolCalls("[see the foo() helper](http://x) for details")).toEqual([]);
  });

  it("does not fire on a function-call-looking phrase mid-sentence (no tokens, not whole-message)", () => {
    expect(parseLiquidToolCalls("then I called Read(path='/a') to inspect it")).toEqual([]);
  });
});
