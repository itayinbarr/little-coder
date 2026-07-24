import { describe, it, expect } from "vitest";
import { readFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import { applyPiPatches, resolvePiRoot, PATCHES } from "./patch-pi.mjs";

// These tests are the upgrade safety-net for our pi source patches.
//
// A source patch can silently stop suppressing pi's UI marker when pi is
// upgraded (the surrounding code shifts and the patch no-ops). We never want
// that to be a silent production regression — so this test FAILS the moment the
// installed pi no longer matches what a patch expects, telling us to refresh
// exactly one string in patch-pi.mjs. A pi bump becomes a loud CI failure, not
// a quiet cosmetic regression for users.

describe("pi runtime patches", () => {
  it("resolves the installed pi package root", () => {
    expect(resolvePiRoot(), "could not locate @earendil-works/pi-coding-agent").toBeTruthy();
  });

  it("applies cleanly and is idempotent", () => {
    // Idempotent: safe to run repeatedly (every launch + tests). There is no
    // postinstall any more — little-coder ships no npm install scripts (#75).
    applyPiPatches();
    applyPiPatches();
    const piRoot = resolvePiRoot();
    for (const p of PATCHES) {
      const file = join(piRoot, p.rel);
      if (!existsSync(file)) continue;
      const src = readFileSync(file, "utf8");
      expect(
        src.includes(p.applied),
        `expected patch marker in ${p.rel} after applying`,
      ).toBe(true);
    }
  });

  it("leaves no un-suppressed original block (loud signal to refresh on pi upgrade)", () => {
    applyPiPatches();
    const piRoot = resolvePiRoot();
    for (const p of PATCHES) {
      const file = join(piRoot, p.rel);
      if (!existsSync(file)) continue;
      const src = readFileSync(file, "utf8");
      // After applying, the original block must be gone — either we replaced it,
      // or this pi version no longer ships it. If pi changed *around* the block
      // so our patch silently no-op'd, the original is still present → fail.
      expect(
        src.includes(p.find),
        `pi patch for "${p.rel}" no longer applies — pi likely changed. ` +
          `Refresh the find/replace in scripts/patch-pi.mjs for the new pi version.`,
      ).toBe(false);
    }
  });

  it("the patched file no longer renders the bare \"Operation aborted\" string", () => {
    applyPiPatches();
    const piRoot = resolvePiRoot();
    const file = join(piRoot, PATCHES[0].rel);
    const src = readFileSync(file, "utf8");
    // The literal only survives inside our explanatory comment, never as the
    // rendered fallback (`: "Operation aborted";`).
    expect(src.includes(': "Operation aborted";')).toBe(false);
  });
});
