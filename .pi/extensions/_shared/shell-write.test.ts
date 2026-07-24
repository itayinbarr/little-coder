import { describe, expect, it } from "vitest";
import {
  detectWriteTargets,
  hasWriteRedirection,
  splitCommandChain,
  stripHeredocBodies,
} from "./shell-write.ts";

describe("detectWriteTargets — issue #70 repros", () => {
  it("catches the exact heredoc rewrite rvanswieten reported", () => {
    const cmd = [
      "cat > backend/main.py << 'ENDOFFILE'",
      "from fastapi import FastAPI",
      "app = FastAPI()",
      "ENDOFFILE",
    ].join("\n");
    expect(detectWriteTargets(cmd)).toEqual([
      { path: "backend/main.py", kind: "redirect" },
    ]);
  });

  it("is not fooled by a different heredoc delimiter", () => {
    // Matching on the delimiter string would have been routed around instantly.
    for (const delim of ["EOF", "'MYMARKER'", '"XX"', "PY"]) {
      const cmd = `cat > App.jsx << ${delim}\nbody\n${delim.replace(/['"]/g, "")}`;
      expect(hasWriteRedirection(cmd)).toBe(true);
    }
  });

  it("catches append, tee, and dd", () => {
    expect(detectWriteTargets("echo x >> pyproject.toml")).toEqual([
      { path: "pyproject.toml", kind: "append" },
    ]);
    expect(detectWriteTargets("echo x | tee -a out.log")).toEqual([
      { path: "out.log", kind: "tee" },
    ]);
    expect(detectWriteTargets("dd if=/dev/zero of=disk.img bs=1M")).toEqual([
      { path: "disk.img", kind: "dd" },
    ]);
  });

  it("catches a redirect with no space before the target", () => {
    expect(detectWriteTargets("cat>main.py")).toEqual([
      { path: "main.py", kind: "redirect" },
    ]);
  });

  it("reports several targets across a chain", () => {
    const writes = detectWriteTargets("echo a > one.txt && echo b >> two.txt");
    expect(writes.map((w) => w.path)).toEqual(["one.txt", "two.txt"]);
  });
});

describe("detectWriteTargets — must not false-positive", () => {
  it("ignores fd duplication", () => {
    expect(detectWriteTargets("make 2>&1")).toEqual([]);
    expect(detectWriteTargets("echo err >&2")).toEqual([]);
    expect(detectWriteTargets("cmd 1>&2")).toEqual([]);
  });

  it("ignores redirects inside quotes", () => {
    expect(detectWriteTargets('grep "a > b" file.txt')).toEqual([]);
    expect(detectWriteTargets("echo 'x >> y'")).toEqual([]);
  });

  it("ignores comparison operators in a heredoc payload", () => {
    // The body is data. Without stripping, `if a > b:` reads as a redirect and
    // `don't` leaves the quote scanner open for the rest of the string.
    const cmd = [
      "cat > cmp.py << 'EOF'",
      "if a > b:",
      "    pass  # don't compare like this",
      "x = [i for i in range(3) if i > 1]",
      "EOF",
    ].join("\n");
    expect(detectWriteTargets(cmd)).toEqual([{ path: "cmp.py", kind: "redirect" }]);
  });

  it("ignores reads: here-strings, heredocs into stdin, and input redirects", () => {
    expect(detectWriteTargets("wc -l < input.txt")).toEqual([]);
    expect(detectWriteTargets("grep foo <<< \"$var\"")).toEqual([]);
    expect(detectWriteTargets("python3 << 'EOF'\nprint(1)\nEOF")).toEqual([]);
  });

  it("ignores process substitution", () => {
    expect(detectWriteTargets("diff <(ls a) >(sort)")).toEqual([]);
  });

  it("returns nothing for ordinary read-only commands", () => {
    for (const cmd of ["ls -la", "git status", "rg pattern src/", "cat README.md"]) {
      expect(detectWriteTargets(cmd)).toEqual([]);
    }
  });
});

describe("splitCommandChain", () => {
  it("splits on unquoted chain operators", () => {
    expect(splitCommandChain("ls && rm -rf / ; echo done | wc -l")).toEqual([
      "ls",
      "rm -rf /",
      "echo done",
      "wc -l",
    ]);
  });

  it("does not split inside quotes", () => {
    expect(splitCommandChain("echo 'a && b' ; ls")).toEqual(["echo 'a && b'", "ls"]);
  });

  it("treats && as one cut, not two", () => {
    expect(splitCommandChain("a && b")).toEqual(["a", "b"]);
  });

  it("does not treat a heredoc body as commands", () => {
    expect(splitCommandChain("cat > f.sh << 'EOF'\nrm -rf /\nEOF")).toEqual([
      "cat > f.sh",
    ]);
  });
});

describe("stripHeredocBodies", () => {
  it("keeps the opening line and drops the body", () => {
    expect(stripHeredocBodies("cat > f << 'EOF'\nbody\nEOF")).toBe("cat > f ");
  });

  it("drops everything after an unterminated heredoc", () => {
    expect(stripHeredocBodies("cat > f << EOF\nbody without terminator")).toBe(
      "cat > f ",
    );
  });

  it("leaves a here-string alone", () => {
    expect(stripHeredocBodies('grep foo <<< "bar"')).toBe('grep foo <<< "bar"');
  });

  it("handles more than one heredoc", () => {
    const cmd = "cat > a << 'E1'\nx\nE1\ncat > b << 'E2'\ny\nE2";
    expect(splitCommandChain(cmd)).toEqual(["cat > a", "cat > b"]);
  });
});
