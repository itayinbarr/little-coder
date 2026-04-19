---
name: recursion-backtracking
type: domain-knowledge
topic: Backtracking
token_cost: 100
keywords: [permutation, combination, subset, backtrack, constraint, generate, valid, recursive, pruning, n-queens, sudoku, exhaustive, all, solutions, choose, pick, arrangement, password, sequence]
user-invocable: false
---
Use backtracking for constraint satisfaction and combinatorial generation: permutations, combinations, subsets, N-queens, sudoku, valid arrangements. Pattern: make a choice, recurse, undo the choice (backtrack). Prune early — skip branches that already violate constraints to avoid exploring dead ends. For subsets: at each element, choose to include or exclude it (2^n total). For permutations: choose each unused element at each position (n! total). Always pass state by reference and undo mutations rather than copying. If the problem says "generate all" or "find all valid," backtracking is usually the right approach.
