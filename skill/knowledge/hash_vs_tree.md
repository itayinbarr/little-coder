---
name: hash-vs-tree
type: domain-knowledge
topic: Data Structure Choice
token_cost: 90
keywords: [lookup, dictionary, dict, set, hash, hashtable, map, frequency, count, unique, duplicate, ordered, sorted, tree, counter, defaultdict, collections]
user-invocable: false
---
Use dict/set (hash table, O(1) avg lookup) for: membership testing, frequency counting, deduplication, grouping by key. Use collections.Counter for frequency counts, defaultdict(list) for grouping. When you need ordered keys or range queries, use sorted containers or bisect on a sorted list. For "find if X exists" or "count occurrences," always reach for a set or dict first — never scan a list repeatedly. If the problem involves pairs summing to a target, use a set to check complements in O(n) instead of O(n^2) nested loops.
