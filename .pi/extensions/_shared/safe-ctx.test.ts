import { describe, it, expect, vi } from "vitest";
import { isStaleCtxError, tryCtx, hasLiveUI } from "./safe-ctx.ts";

const STALE = new Error(
  "This extension ctx is stale after session replacement or reload. Do not use a captured pi or command ctx after ctx.newSession(), ctx.fork(), ctx.switchSession(), or ctx.reload().",
);

describe("isStaleCtxError", () => {
  it("recognises pi's invalidation error", () => {
    expect(isStaleCtxError(STALE)).toBe(true);
    expect(isStaleCtxError("This extension ctx is stale ...")).toBe(true);
  });
  it("does not claim unrelated errors", () => {
    expect(isStaleCtxError(new Error("ECONNREFUSED"))).toBe(false);
    expect(isStaleCtxError(undefined)).toBe(false);
  });
});

describe("tryCtx", () => {
  it("returns the value when the ctx is live", () => {
    expect(tryCtx(() => 42, 0)).toBe(42);
  });
  it("falls back when the ctx has been invalidated", () => {
    expect(tryCtx(() => { throw STALE; }, "fallback")).toBe("fallback");
  });
  it("rethrows anything that is not a stale ctx, so real bugs still surface", () => {
    expect(() => tryCtx(() => { throw new TypeError("setWidget is not a function"); }, null))
      .toThrow("setWidget is not a function");
  });
});

describe("hasLiveUI", () => {
  it("is false for a missing ctx and for a disposed one", () => {
    expect(hasLiveUI(undefined)).toBe(false);
    expect(hasLiveUI(null)).toBe(false);
    const dead = { get hasUI(): boolean { throw STALE; } };
    expect(hasLiveUI(dead)).toBe(false);
  });
  it("reflects a live ctx", () => {
    expect(hasLiveUI({ hasUI: true })).toBe(true);
    expect(hasLiveUI({ hasUI: false })).toBe(false);
  });
  it("does not swallow a non-stale throw", () => {
    const broken = { get hasUI(): boolean { throw new RangeError("boom"); } };
    expect(() => hasLiveUI(broken)).toThrow("boom");
  });
});
