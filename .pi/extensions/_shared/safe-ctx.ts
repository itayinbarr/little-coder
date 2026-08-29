// Guarding extension code against a pi context that has been invalidated.
//
// pi hands extensions a live `ctx` whose every accessor is a getter that calls
// `assertActive()`. When a session is replaced or torn down (`/new`, `/clear`,
// fork, switch, reload, quit, and `/implement` since v1.18.0) pi calls
// `AgentSession.dispose()`, which invalidates the WHOLE extension runtime:
//
//   invalidate(message = "This extension ctx is stale after session replacement
//   or reload. ...") { if (!this.staleMessage) { this.staleMessage = message; ... } }
//
// From that moment `ctx.ui`, `ctx.hasUI`, `ctx.mode`, `pi.sendUserMessage()` and
// the rest all THROW rather than returning something falsy. Any extension that
// holds a ctx and touches it from something asynchronous (a timer, a child
// process event, a completion callback) is therefore one race away from an
// uncaught exception that takes the whole agent down. That is not theoretical:
// it is #108 (context watchdog, compaction callback) and #119 (bg-shell, child
// `close` event after `/new`), reported three weeks apart with the same trace.
//
// The rule this file encodes: reading from a captured ctx is allowed, but it
// must never be the reason the process dies. `tryCtx` swallows exactly the
// stale-ctx error and rethrows anything else, so a genuine bug in a UI call
// still surfaces instead of being silently eaten.

/** True for pi's extension-runtime-invalidated error, and nothing else. */
export function isStaleCtxError(err: unknown): boolean {
  const message = err instanceof Error ? err.message : String(err ?? "");
  return message.includes("extension ctx is stale");
}

/**
 * Read from (or write through) a possibly-stale ctx.
 *
 * Returns `fn()`, or `fallback` if the ctx has been invalidated. Errors that
 * are NOT the stale-ctx error propagate: a `setWidget` that throws for some
 * other reason is a real bug and should not be hidden by this helper.
 */
export function tryCtx<T>(fn: () => T, fallback: T): T {
  try {
    return fn();
  } catch (err) {
    if (isStaleCtxError(err)) return fallback;
    throw err;
  }
}

/** `ctx.hasUI` for a ctx that may already be gone. A dead session has no UI. */
export function hasLiveUI(ctx: { hasUI?: boolean } | null | undefined): boolean {
  if (!ctx) return false;
  return tryCtx(() => ctx.hasUI === true, false);
}
