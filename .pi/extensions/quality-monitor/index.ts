import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { assessResponse, buildCorrectionMessage, phraseForUser, type ToolCall } from "./quality.ts";
import { harnessIntervention } from "../_shared/intervention.ts";

// Port of local/quality.py. Hooks turn_end, inspects the assistant message
// + previous turn's tool calls, and — if we detect a failure mode — sends
// a correction user message with deliverAs:"steer" so the model gets it
// immediately on its next turn rather than waiting for the next user input.

// Session-scoped state. Pi reuses extensions across turns within a session;
// a fresh extension instance is loaded per session via the session lifecycle.
let previousToolCalls: ToolCall[] = [];
let consecutiveFailures = 0;
const MAX_CONSECUTIVE_CORRECTIONS = 2; // stop nudging after 2 failed corrections

export default function (pi: ExtensionAPI) {
  // Populate the known-tools set lazily by observing tool_execution events.
  // This avoids needing to read pi's tool registry directly.
  const knownTools = new Set<string>();
  pi.on("tool_execution_start", async (event) => {
    const name = (event as any).toolName;
    if (typeof name === "string") knownTools.add(name);
  });

  pi.on("session_start", async () => {
    previousToolCalls = [];
    consecutiveFailures = 0;
  });

  pi.on("turn_end", async (event, ctx) => {
    const message = (event as any).message;
    if (!message) return;

    // Skip turns that were interrupted/aborted — by the user pressing ESC OR by
    // a harness abort (thinking-budget, turn-cap). pi marks these with
    // stopReason "aborted"; their content is legitimately partial/empty, so
    // assessing them spuriously fires `empty_response` and steers a "your
    // previous response was empty" correction onto the user's NEXT prompt
    // (the escape-interrupt bug, and the second false warning in the
    // thinking-budget cascade). An aborted turn is not a model quality failure.
    if (message.stopReason === "aborted") return;

    // Skip turns that ended in a provider/transport error (pi marks these
    // stopReason "error"). An API 400 — e.g. an ollama model that rejects the
    // requested thinking level (issue #86) — leaves the content empty, which
    // `assessResponse` would read as `empty_response` and "correct" by re-sending
    // the same request 3× before backing off, burying pi's real error under
    // three "your previous response was empty" lines. Steering a correction
    // can't fix a 400. pi already renders the actual error; we add one targeted
    // hint for the thinking case, whose fix (lower the thinking level) isn't
    // obvious from the raw message, then stop.
    if (message.stopReason === "error") {
      const errMsg = typeof message.errorMessage === "string" ? message.errorMessage : "";
      if (/does not support thinking|reasoning setting .*is not supported/i.test(errMsg)) {
        harnessIntervention(
          ctx,
          "this model rejected the requested thinking level — lower it with " +
            "shift+tab (thinking cycle) or in /settings, or pick a model that supports thinking.",
        );
      }
      return;
    }

    // Extract assistant text + tool calls from pi's content-block format
    const content = Array.isArray(message.content) ? message.content : [];
    const text = content
      .filter((c: any) => c?.type === "text")
      .map((c: any) => c.text ?? "")
      .join("\n");
    const currentCalls: ToolCall[] = content
      .filter((c: any) => c?.type === "toolCall")
      .map((c: any) => ({ name: c.name, input: c.arguments ?? c.input ?? {} }));

    const verdict = assessResponse(text, currentCalls, previousToolCalls, knownTools);

    // Update rolling state for next turn regardless of verdict
    previousToolCalls = currentCalls;

    if (verdict.ok) {
      consecutiveFailures = 0;
      return;
    }

    // Cap corrections so we don't burn turns in a correction loop
    consecutiveFailures++;
    if (consecutiveFailures > MAX_CONSECUTIVE_CORRECTIONS) {
      harnessIntervention(
        ctx,
        `${phraseForUser(verdict.reason)} — backing off after ${consecutiveFailures} in a row.`,
      );
      return;
    }

    const correction = buildCorrectionMessage(verdict.reason);
    harnessIntervention(ctx, `${phraseForUser(verdict.reason)} — redirecting the model.`);
    // "steer" delivers the correction promptly to the in-flight loop. The
    // prior "followUp" mode parked the message until the *next* user input,
    // by which point it was no longer relevant (issue #16).
    pi.sendUserMessage(correction, { deliverAs: "steer" });
  });
}
