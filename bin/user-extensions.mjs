// The user extension directory — a place to drop your own extensions that
// survives upgrades and needs no env var (issues #67, #69).
//
// little-coder launches pi with `--no-extensions` and then loads exactly its
// own bundled set. That's what keeps the cold-start context around 7k tokens
// instead of the 20k+ a fully-loaded agent starts with, and it's why nothing
// in your cwd can silently change behavior mid-task. The cost is that there
// was no first-class way to add anything of your own: `LITTLE_CODER_EXTRA_
// EXTENSIONS` worked but nobody found it, and the fallback people reached for
// was forking the installed npm package (issue #46).
//
// So: a directory that is loaded if it exists and ignored if it doesn't. No
// default content, nothing created implicitly — an install that never touches
// it behaves exactly as before.
//
// Resolution order mirrors the models.json override
// (bin/little-coder.mjs::resolveUserModelsPath):
//
//   $LITTLE_CODER_EXTENSIONS_DIR
//     → $XDG_CONFIG_HOME/little-coder/extensions
//     → ~/.config/little-coder/extensions
//
// Each direct child is one extension: a `.ts`/`.js`/`.mjs` file, or a
// directory containing `index.ts` / `index.js`. Entries that don't resolve
// produce a one-line warning and are skipped, never a failed launch.

import { existsSync, readdirSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

const EXTENSION_FILE = /\.(ts|js|mjs)$/;

/**
 * Where the user extension directory lives, or undefined if we can't tell.
 * Returns the path whether or not it exists — callers decide what absence means.
 */
export function resolveUserExtensionsDir(env = process.env, home = homedir()) {
  const explicit = env.LITTLE_CODER_EXTENSIONS_DIR;
  if (explicit && explicit.trim().length > 0) {
    const t = explicit.trim();
    if (t === "~") return home;
    if (t.startsWith("~/")) return home + t.slice(1);
    return t;
  }
  if (env.XDG_CONFIG_HOME) {
    return join(env.XDG_CONFIG_HOME, "little-coder", "extensions");
  }
  const h = env.HOME || env.USERPROFILE || home;
  if (h) return join(h, ".config", "little-coder", "extensions");
  return undefined;
}

/**
 * Resolve every extension entry point in the user extension directory.
 *
 * @returns {{ dir: string|undefined, entries: string[], warnings: string[] }}
 *   `entries` are absolute paths to pass to pi as `--extension <entry>`;
 *   `warnings` are one-liners to print to stderr. A missing directory is the
 *   normal case and produces neither.
 */
export function discoverUserExtensions(
  env = process.env,
  { home = homedir(), exists = existsSync, stat = statSync, readdir = readdirSync } = {},
) {
  const dir = resolveUserExtensionsDir(env, home);
  const entries = [];
  const warnings = [];
  if (!dir || !exists(dir)) return { dir, entries, warnings };

  let names;
  try {
    if (!stat(dir).isDirectory()) {
      warnings.push(`little-coder: user extensions path is not a directory, skipping: ${dir}`);
      return { dir, entries, warnings };
    }
    names = readdir(dir).sort();
  } catch (err) {
    warnings.push(
      `little-coder: could not read user extensions dir (${err?.message ?? err}), skipping: ${dir}`,
    );
    return { dir, entries, warnings };
  }

  for (const name of names) {
    // Dotfiles and node_modules are housekeeping, not extensions — skipping
    // them silently keeps `npm install`ing a dependency in there from
    // producing a wall of warnings.
    if (name.startsWith(".") || name === "node_modules" || name === "package.json") continue;
    const full = join(dir, name);
    try {
      if (stat(full).isDirectory()) {
        const index = [join(full, "index.ts"), join(full, "index.js")].find((p) => exists(p));
        if (!index) {
          warnings.push(
            `little-coder: user extension has no index.ts/index.js, skipping: ${full}`,
          );
          continue;
        }
        entries.push(index);
        continue;
      }
      if (EXTENSION_FILE.test(name)) {
        entries.push(full);
        continue;
      }
      // A stray README/notes file is not worth warning about; anything else
      // that looks intentional is.
      if (!/\.(md|txt|json|lock)$/.test(name)) {
        warnings.push(`little-coder: not an extension (need .ts/.js/.mjs), skipping: ${full}`);
      }
    } catch {
      // unreadable / racing stat — skip silently
    }
  }

  return { dir, entries, warnings };
}
