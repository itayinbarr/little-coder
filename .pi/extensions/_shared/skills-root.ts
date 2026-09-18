// Where the skill card packs live, resolved by SEARCHING rather than by
// counting directories.
//
// skill-inject and knowledge-inject each used `join(here, "..", "..", "..",
// "skills")`, which is correct for the little-coder checkout (an extension
// sits at `.pi/extensions/<name>/`, so three levels up is the package root)
// and wrong everywhere else. The pi package built by `scripts/build-pi-package.mjs`
// lays extensions out at `extensions/<name>/`, two levels up, so both
// extensions resolved a path that does not exist.
//
// The failure was silent by construction: both loaders end with
// `if (!existsSync(dir)) return;`, so a pi-package user would have got the
// extensions with none of their content and no way to tell. Searching upward
// for the directory is correct in both layouts and stays correct in whatever
// layout comes next.

import { existsSync } from "node:fs";
import { dirname, join } from "node:path";

/** Nearest ancestor of `startDir` containing a `skills/` directory, or
 *  undefined. Bounded by the filesystem root; `depth` caps the walk so a
 *  pathological mount cannot spin. */
export function findSkillsRoot(startDir: string, exists: (p: string) => boolean = existsSync): string | undefined {
  let dir = startDir;
  for (let depth = 0; depth < 8; depth++) {
    if (exists(join(dir, "skills"))) return join(dir, "skills");
    const parent = dirname(dir);
    if (parent === dir) return undefined;
    dir = parent;
  }
  return undefined;
}

/** A named pack under the skills root (`tools`, `knowledge`, `protocols`), or
 *  undefined when neither the root nor the pack is present. */
export function skillPackDir(startDir: string, pack: string): string | undefined {
  const root = findSkillsRoot(startDir);
  if (!root) return undefined;
  const dir = join(root, pack);
  return existsSync(dir) ? dir : undefined;
}
