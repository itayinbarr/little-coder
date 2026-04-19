---
name: write-guidance
type: tool-guidance
target_tool: Write
priority: 10
token_cost: 110
user-invocable: false
---
## Write Tool
Create a **new** file with the given content. Creates parent directories automatically.

REQUIRED: file_path (absolute), content (full file content)

**Write is for creating new files only.** If the file already exists, Write will be **refused** by the tool and return an error telling you to use Edit instead. Do not retry Write on the same path — it will be refused again.

WHEN TO USE Write:
- The file does not exist yet and you are creating it from scratch

WHEN TO USE Edit INSTEAD:
- ANY change to an existing file — bug fixes, refactors, format tweaks, adding a function, renaming a variable, everything. Edit takes old_string + new_string and patches in place.
- Iterating after a failed test — never retype the whole file

If you need to completely replace an existing file's content, Edit can still do that: pass the entire current content as old_string and the full new content as new_string. Read the file first if you don't already have its current content.

EXAMPLE:
```tool
{"name": "Write", "input": {"file_path": "/tmp/example/new_module.py", "content": "def hello():\n    return 'hi'\n"}}
```
NOTE: Always use the EXACT file path given in the task, never a placeholder.
