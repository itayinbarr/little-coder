# Extending little-coder

little-coder starts pi with `--no-extensions` and then loads exactly its own bundled set. That is deliberate: it's what keeps the cold-start context around **7k tokens** instead of the 20k+ a fully-loaded agent begins with, and it means nothing in your working directory can silently change how the agent behaves mid-task. On an 8 GB card, context you spend before the first prompt is context you don't get back.

The cost of that choice is that adding anything of your own used to mean editing the installed npm package. This page is the supported way to do it instead.

Three layers, in increasing order of "I want the whole pi ecosystem":

1. [Your own extensions directory](#your-own-extensions-directory) — the normal path
2. [`LITTLE_CODER_EXTRA_EXTENSIONS`](#pointing-at-extensions-somewhere-else) — point at files anywhere
3. [`--with-pi-extensions`](#loading-pis-own-extensions) — let pi discover its own

Everything here is opt-in. A little-coder install that uses none of it behaves exactly as it always has.

---

## Your own extensions directory

Drop extensions in:

```
~/.config/little-coder/extensions/
```

(or `$XDG_CONFIG_HOME/little-coder/extensions/`, or wherever `LITTLE_CODER_EXTENSIONS_DIR` points).

Each direct child is one extension:

```
~/.config/little-coder/extensions/
├── telegram-bridge.ts        ← a single file
├── my-linter/
│   └── index.ts              ← or a directory with an index.ts / index.js
└── notes.md                  ← ignored
```

They load **after** the bundled set on every launch, so yours can override bundled behavior rather than being shadowed by it. The directory is never created for you and nothing is added to it — if it doesn't exist, nothing happens.

Check what actually loaded with **`/extensions`** inside the TUI:

```
◆ extensions  (/extensions to close)
  bundled   32 loaded
  yours      2 loaded
      ~/.config/little-coder/extensions/telegram-bridge.ts
      ~/.config/little-coder/extensions/my-linter/index.ts
  pi extensions off — relaunch with --with-pi-extensions
```

An extension that fails to resolve is reported there and as a notification at session start, rather than scrolling past on stderr before the TUI paints.

### Writing one

An extension is a module with a default-exported function that receives pi's `ExtensionAPI`:

```ts
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";

export default function (pi: ExtensionAPI) {
  pi.registerCommand("hello", {
    description: "Say hello",
    handler: async (args, ctx) => {
      ctx.ui.notify(`hello ${args || "world"}`, "info");
    },
  });
}
```

TypeScript is loaded directly — no build step. The bundled extensions in [`.pi/extensions/`](../.pi/extensions) are the best reference; they're all small, and each one opens with a comment explaining why it exists. Useful starting points:

| Want to… | Look at |
|---|---|
| Add a slash command | [`clear-command`](../.pi/extensions/clear-command), [`update-notice`](../.pi/extensions/update-notice) |
| Add a tool | [`extra-tools`](../.pi/extensions/extra-tools), [`shell-session`](../.pi/extensions/shell-session) |
| Block or rewrite a tool call | [`write-guard`](../.pi/extensions/write-guard), [`permission-gate`](../.pi/extensions/permission-gate) |
| Add per-turn context | [`skill-inject`](../.pi/extensions/skill-inject) — and read [`_shared/inject.ts`](../.pi/extensions/_shared/inject.ts) first |
| Add a hotkey + panel | [`shortcuts-help`](../.pi/extensions/shortcuts-help), [`plan-mode`](../.pi/extensions/plan-mode) |
| Add a model provider | [`llama-cpp-provider`](../.pi/extensions/llama-cpp-provider) |

Two things worth knowing before you write one:

- **Don't rewrite the system prompt per turn.** It's the first thing in every request, so changing it invalidates the whole cached prefix and your server reprocesses the entire conversation. Return a `message` from `before_agent_start` instead — `_shared/inject.ts` wraps this. (This was [#73](https://github.com/itayinbarr/little-coder/issues/73).)
- **Cap every rendered line to the terminal width.** pi-tui throws on overflow; `_shared/width.ts` has `truncateLineToWidth`.

## Pointing at extensions somewhere else

`LITTLE_CODER_EXTRA_EXTENSIONS` takes a path-delimited list (`:` on POSIX, `;` on Windows) of files or directories, loaded between the bundled set and your extensions directory:

```bash
LITTLE_CODER_EXTRA_EXTENSIONS=~/.local/lib/node_modules/pi-ponytail/extensions/ponytail.js little-coder
```

Use this when the extension lives inside another installed package and you'd rather not copy or symlink it. For a one-off, `little-coder -e <path>` still works.

## Loading pi's own extensions

little-coder bundles pi as an internal dependency, so a pi extension installed globally isn't visible to it by default. To let pi discover its own extensions from `~/.pi/agent/extensions` and `./.pi/extensions`:

```bash
little-coder --with-pi-extensions
# or
LITTLE_CODER_PI_EXTENSIONS=1 little-coder
```

little-coder prints a notice when this is on, because the guarantee it gives up is real: the extension set is no longer fixed, the cold-start context grows by whatever those extensions add, and a repository you cloned can now contribute extensions from its `.pi/` directory. pi's own trust prompt still gates project-local code before anything runs, but treat this the way you'd treat any "run code from this repo" switch.

**Themes are not affected by any of this.** `--no-extensions` gates extensions only, so pi themes in `~/.pi/agent/themes` and `./.pi/themes` have always loaded normally.

---

## Community extensions

Built something? Open an issue or PR and it goes on this list. These are **community projects, not part of little-coder** — they aren't bundled, reviewed, or supported here, and you should read anything you install.

| What | By | Where |
|---|---|---|
| **Zed / ACP bridge** — run little-coder as an external agent inside Zed via `pi-acp`, with a wrapper that starts and stops `llama-server` alongside it | [@BMorgan1296](https://github.com/BMorgan1296), with [@charly1r](https://github.com/charly1r) | [`docs/zed-acp.md`](zed-acp.md), [svkozak/pi-acp](https://github.com/svkozak/pi-acp), [#58](https://github.com/itayinbarr/little-coder/issues/58) |
| **Telegram bridge** — drive little-coder from Telegram, using the repo's own `benchmarks/rpc_client.py` so you get the same extensions, `AGENTS.md`, and speed as the terminal | [@johnzan](https://github.com/johnzan) | [#69](https://github.com/itayinbarr/little-coder/issues/69) |
| **llama.cpp configs + local model recommendations** — an ongoing thread of tested configs and blind-tournament model results on consumer hardware | [@charly1r](https://github.com/charly1r) | [#63](https://github.com/itayinbarr/little-coder/issues/63) |

AI-assisted contributions are welcome — that's rather the point of the project. What matters is that it works and that you can explain what it does.
