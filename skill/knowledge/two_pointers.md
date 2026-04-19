---
name: two-pointers
type: domain-knowledge
topic: Two Pointers and Sliding Window
token_cost: 100
keywords: [pointer, two, sliding, window, substring, subarray, pair, sum, target, sorted, left, right, fast, slow, cycle, linked, list, contiguous, consecutive, squeeze]
user-invocable: false
---
Two pointers on a sorted array: start left=0, right=n-1, move inward based on comparison — solves pair-sum, three-sum, container problems in O(n). Sliding window for contiguous subarrays/substrings: expand right boundary, shrink left when constraint violated — solves "longest/shortest substring with property" in O(n). Fast/slow pointers: detect cycles in linked lists (Floyd's), find middle element. Key insight: if brute force is O(n^2) nested loops over a sorted or sequential structure, two pointers likely reduces it to O(n).
