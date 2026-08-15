---
name: research-protocol
type: workflow
triggers: ["/research"]
when_to_use: when the task requires gathering facts from the web and citing them in a final answer
context: inline
token_cost: 180
requires_tools: [BrowserNavigate, BrowserExtract, EvidenceAdd, EvidenceList]
user_invocable: false
---
## Research Protocol (evidence-first)

1. Decompose the question into one or two unknowns. Write them down in your first reply.
2. For each unknown, run BrowserNavigate → BrowserExtract → EvidenceAdd (one fact per entry).
3. Do NOT state a fact that isn't backed by an EvidenceAdd id.
4. Before answering, call EvidenceList. Your answer must reference at least one id.
5. If EvidenceList is empty, you are not ready to answer — go back to step 2.

Stop conditions:
- You have an evidence id for every claim in your answer → ANSWER.
- You have tried 3+ search refinements with no usable evidence → say "insufficient evidence" instead of guessing.
