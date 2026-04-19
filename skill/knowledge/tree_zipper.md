---
name: tree-zipper
type: domain-knowledge
topic: Functional Tree Navigation
token_cost: 130
keywords: [zipper, tree navigation, breadcrumb, focus, up, down, left, right, functional tree, immutable tree, cursor]
user-invocable: false
---
A tree zipper is a cursor for immutable trees. State = (focus, trail). focus is the current subtree. trail is a list of "breadcrumbs" describing the path from root to focus — each crumb remembers the parent's value plus the siblings NOT taken. Operations: down_left/down_right push a crumb (remembering current node + the other child) and make the chosen child the new focus. up pops the top crumb, rebuilds the parent by combining it with the current focus, and makes that parent the new focus. set_value replaces the focused subtree's value. to_tree walks all the way up (repeated up) to rebuild the whole tree. Key invariant: you can always reconstruct the full original tree from (focus, trail) — no information is lost. Equality of two zippers = equality of the fully-reconstructed trees, NOT of the raw (focus, trail) pairs, because different trails can represent the same tree position.
