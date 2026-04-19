---
name: workspace-docs
type: domain-knowledge
topic: Workspace Documentation
token_cost: 140
keywords: [implement, build, create, fix, task, exercise, feature, todo, spec, specification, requirements, instructions, bug, test, failing, review, refactor]
requires_tools: [Read, Glob]
user-invocable: false
---
Before writing code for a non-trivial task, check if the workspace has a problem specification or convention document. These are cheap to read and often contain the exact format rules, edge cases, or constraints the tests assert — which the model would otherwise have to reverse-engineer from tests alone. Look for (in priority order): `.docs/instructions.md` and `.docs/instructions.append.md` (exercism-style problem specs), `AGENTS.md` / `CLAUDE.md` (agent-specific instructions at repo root), `README.md` in the current directory, `SPEC.md` / `SPECIFICATION.md`, and `docs/*.md`. Use Glob to discover them (`*.md`, `.docs/*.md`, `AGENTS.md`) and Read the relevant one. Do this ONCE at the start of a task, not every turn. If the spec disambiguates a failing test (e.g. "the first and last elements must match" or "spaces and punctuation are excluded"), that single read saves many debug iterations. Skip for pure read-only questions — only invest the Read call when you are about to change code.
