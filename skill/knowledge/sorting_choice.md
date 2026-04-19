---
name: sorting-choice
type: domain-knowledge
topic: Sorting
token_cost: 90
keywords: [sort, order, rank, largest, smallest, kth, median, arrange, compare, stable, priority, heap, nlargest, nsmallest, key, reverse, sorted]
user-invocable: false
---
Python's built-in sorted()/list.sort() is Timsort — O(n log n), stable, and almost always the right choice. Use key= for custom ordering. For top-k elements, use heapq.nlargest/nsmallest (O(n log k)) instead of full sort. For finding just the kth element, consider quickselect or statistics.median. Counting sort / radix sort help only when values are bounded integers. When the problem says "sort by X then by Y," use a tuple key: key=lambda x: (x.a, x.b). For reverse on one field only, negate it or use functools.cmp_to_key.
