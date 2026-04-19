---
name: binary-search
type: domain-knowledge
topic: Binary Search
token_cost: 90
keywords: [binary, search, sorted, monotonic, bisect, minimum, maximum, feasible, predicate, lower, upper, bound, log, efficient, mid, pivot, rotated]
user-invocable: false
---
Binary search works on any monotonic predicate, not just sorted arrays. Pattern: "find minimum X such that condition(X) is true" — binary search on the answer space. Use bisect.bisect_left/bisect_right for sorted-array insertion points. For "minimize the maximum" or "maximize the minimum" problems, binary search on the answer and check feasibility. Always use lo + (hi - lo) // 2 to avoid overflow. When searching rotated arrays, check which half is sorted first. Time: O(log n) — whenever you see "sorted" or "monotonic" in a problem, consider binary search.
