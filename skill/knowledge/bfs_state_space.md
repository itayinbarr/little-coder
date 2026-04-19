---
name: bfs-state-space
type: domain-knowledge
topic: State-Space Search
token_cost: 120
keywords: [bucket, pouring, state space, minimum moves, shortest sequence, reach goal, transitions, visited states, water, pour, fill, empty]
user-invocable: false
---
When a problem asks for the MINIMUM number of moves/steps to reach a goal state (bucket pouring, puzzle solving, sliding tiles), model it as BFS over a state space. State = a tuple of all values that fully describe the situation (e.g. (bucket_a, bucket_b)). From each state, enumerate every legal transition (fill A, fill B, empty A, empty B, pour A→B, pour B→A) and produce the next state. Use a visited set keyed on the state tuple to avoid cycles. BFS from the start state; the first time you pop a state matching the goal, its distance is the minimum move count. Track which bucket holds the goal and the other bucket's value at that point. Edge case: if start_bucket is forbidden as an immediate "fill the wrong one first" move, encode that as a filter on the initial transitions.
