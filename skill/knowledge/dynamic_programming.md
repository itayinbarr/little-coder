---
name: dynamic-programming
type: domain-knowledge
topic: Dynamic Programming
token_cost: 110
keywords: [dynamic programming, dp, memoize, memoization, tabulation, subproblem, overlapping, optimal substructure, fibonacci, knapsack, longest, subsequence, minimum cost, maximum profit, number of ways, climb, stairs, coins, edit distance]
user-invocable: false
---
Use dynamic programming when a problem has overlapping subproblems (same computation repeated) and optimal substructure (optimal solution built from optimal sub-solutions). Signs: "find minimum cost," "count the number of ways," "longest/shortest subsequence," "can you reach." Define state (what changes between subproblems) and recurrence (how states relate). Top-down with @cache is easiest to write; bottom-up tabulation avoids recursion limits and is often faster. Always check if you can reduce space by keeping only the previous row/state instead of the full table.
