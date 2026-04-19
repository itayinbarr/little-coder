---
name: webfetch-guidance
type: tool-guidance
target_tool: WebFetch
priority: 6
token_cost: 80
user-invocable: false
---
## WebFetch Tool
Fetch and extract content from a URL.

REQUIRED: url (full URL starting with http:// or https://)

RULES:
- Always use complete URLs with protocol
- Returns extracted text content (HTML stripped)
- Good for reading documentation, API references, web pages

EXAMPLE:
```tool
{"name": "WebFetch", "input": {"url": "https://docs.python.org/3/library/json.html"}}
```
