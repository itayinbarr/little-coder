---
name: dfs-vs-bfs
type: domain-knowledge
topic: Graph Traversal
token_cost: 100
keywords: [dfs, bfs, depth, breadth, graph, traverse, path, maze, shortest, connected, reachable, visited, queue, stack, neighbor, walk, flood, fill, island]
user-invocable: false
---
DFS (stack/recursion) explores one branch fully before backtracking — use for: cycle detection, topological sort, path existence, connected components, backtracking puzzles, flood fill. BFS (queue) explores level-by-level — use for: shortest unweighted path, level-order traversal, nearest neighbor, minimum steps. If the problem asks "shortest" or "minimum steps" on an unweighted graph, always choose BFS. If it asks "all paths," "can we reach," or "count islands," DFS is simpler. Both visit each node once: O(V+E) time.
