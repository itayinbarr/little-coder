---
name: tree-rerooting
type: domain-knowledge
topic: Tree Re-Rooting (POV)
token_cost: 120
keywords: [re-root, reroot, pov, point of view, tree rotation, change root, from_pov, reparent, path between nodes, undirected tree]
user-invocable: false
---
Re-rooting an undirected tree from a new node: build an undirected adjacency map (parent↔children become symmetric neighbor sets), then do DFS/BFS from the target node. Every node you visit gets its parent set to the node you came from, and its children become all neighbors minus that parent. The result is a new rooted tree with the target as root. Path-between(a, b): re-root at a, then walk from b up parent pointers until you hit a — that gives the reversed path; reverse it for a→b order. If the target node is not in the tree, return None (not an error — many test suites treat "node absent" as None). Cost: O(N) per re-root. Do NOT mutate the original tree when re-rooting — build a fresh node structure, so repeated from_pov calls on the original work correctly.
