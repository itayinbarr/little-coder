---
name: shell-start-guidance
type: tool-guidance
target_tool: ShellStart
priority: 10
token_cost: 210
user-invocable: false
---
## `ShellStart` Tool
Run a long command in the background and return immediately. `bash` blocks the
whole turn until the command exits; `ShellStart` does not.

REQUIRED: command (shell command string)
OPTIONAL: label (short name), wake_on (what should interrupt you)

USE IT FOR: training runs, builds, `npm install`, test suites, servers,
watchers — anything that takes minutes. Use plain `bash` for quick commands.

### You will be woken automatically — do NOT poll
Declare what matters in `wake_on` and then GET ON WITH OTHER WORK. You will be
sent a message when something worth knowing happens. Calling `ShellLog` in a
loop to "check on it" wastes the entire point of this tool: a six-hour job
checked every five minutes is 71 useless turns.

`wake_on` fields (all optional):
- `exit` — wake when it finishes (default true)
- `match` — text or regex worth waking for, e.g. `["Traceback", "val_loss="]`
- `silence` — wake if it goes quiet this long after producing output, e.g. `"10m"`
- `every_n_matches` — only wake on every Nth match, to throttle a chatty pattern

EXAMPLE — a training run where only a crash or every 10th eval matters:
```tool
{"name": "ShellStart", "input": {"command": "python train.py --epochs 50", "label": "finetune", "wake_on": {"match": ["Traceback", "CUDA out of memory", "val_loss="], "every_n_matches": 10, "silence": "15m"}}}
```

EXAMPLE — a build you only care about the end of:
```tool
{"name": "ShellStart", "input": {"command": "npm run build", "label": "build"}}
```

RELATED: `ShellList` (what is running), `ShellLog` (read output when you have a
reason to), `ShellSend` (write to stdin), `ShellStop` (kill it).
