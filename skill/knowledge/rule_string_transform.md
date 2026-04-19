---
name: rule-string-transform
type: domain-knowledge
topic: Ordered-Rule String Transformation
token_cost: 120
keywords: [pig latin, string rule, transform word, vowel, consonant, cluster, qu, ordered rules, first match, prefix, suffix, translate word]
user-invocable: false
---
For rule-based string transforms (pig latin, atbash, rot, etc.): encode the rules as an ordered list of (predicate, transform) pairs. For each word, walk the list; apply the FIRST matching rule and stop. Order matters — specific rules must come before general ones. Pig latin gotchas: (1) a "qu" or consonant-cluster-ending-in-qu counts as a unit — "quick" → "ickquay", "square" → "aresquay"; (2) "y" acts as a consonant at the start but a vowel in the middle — "yellow" → "ellowyay", "rhythm" → "ythmrhay"; (3) the rule order that works is: starts-with-vowel-or-xr-or-yt → append "ay"; starts-with-consonant(s)-then-"qu" → move cluster+qu, append "ay"; starts-with-consonants-up-to-first-"y"-or-vowel → move the consonants, append "ay"; fallback → append "ay". Always test each rule in isolation before combining.
