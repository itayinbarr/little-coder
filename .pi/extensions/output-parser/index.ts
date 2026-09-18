import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { filterKnownTools, parseTextToolCalls } from "./parser.ts";
import { harnessIntervention } from "../_shared/intervention.ts";

// Detects malformed/fenced tool calls in assistant text and nudges the model
// back onto native tool-calling. Active-repair (executing extracted calls
// and synthesizing tool_result messages) is intentionally not attempted on
// the headline Qwen3.6-35B-A3B path, which uses native tool calling. When
// extracted calls ARE detected, we log them via ctx.ui.notify and queue a
// follow-up nudge for the next turn.
//
// One format is handled differently: LFM2/Liquid "Pythonic" tool calls
// (`<|tool_call_start|>[Read(path='…')]<|tool_call_end|>`, issue #42). Pythonic
// IS that model's native channel, so a "use native tool calls" nudge can't move
// it to another format — it would just re-emit the same text every turn and
// loop. little-coder also can't execute the calls itself (pi exposes no
// extension API to run a tool + synthesize its result). So for that format we
// surface a single, accurate diagnostic pointing at the real fix — serving
// llama.cpp with `--jinja` and the model's chat template, which parses the
// calls into native tool_calls upstream — instead of looping a futile nudge.

function extractAssistantText(message: any): string {
  if (!message) return "";
  const content = message.content;
  if (typeof content === "string") return content;
  if (Array.isArray(content)) {
    return content.filter((c) => c?.type === "text").map((c) => c.text).join("\n");
  }
  return "";
}

function hasNativeToolCalls(message: any): boolean {
  const content = message?.content;
  if (!Array.isArray(content)) return false;
  return content.some((c: any) => c?.type === "toolCall");
}

export default function (pi: ExtensionAPI) {
  // The --jinja diagnostic is shown once per session — every LFM2 turn would
  // otherwise repeat it, which is noise once the user knows.
  let liquidNotified = false;

  pi.on("turn_end", async (event, ctx) => {
    const message = (event as any).message;
    if (!message) return;
    // If pi already detected native tool calls, nothing to rescue.
    if (hasNativeToolCalls(message)) return;
    const text = extractAssistantText(message);
    if (!text) return;

    // Only nudge about tools that exist. A name the session has never heard of
    // cannot be "re-issued as a native tool call" by anyone, so an intervention
    // about one is an instruction the model cannot follow (issue #96).
    // getAllTools() is the full configured set rather than the currently ACTIVE
    // one: a real tool that tool-gating has parked for this phase is still a
    // slip worth catching, and treating it as prose would be the same bug in
    // the other direction. A ctx without the accessor filters nothing.
    let knownNames: string[] | undefined;
    try {
      const all = (ctx as any)?.getAllTools?.();
      if (Array.isArray(all)) knownNames = all.map((t: any) => String(t?.name ?? "")).filter(Boolean);
    } catch {
      knownNames = undefined;
    }

    const calls = filterKnownTools(parseTextToolCalls(text), knownNames);
    if (calls.length === 0) return;

    const liquidCalls = calls.filter((c) => c.format === "liquid");
    const otherCalls = calls.filter((c) => c.format !== "liquid");

    // LFM2/Liquid Pythonic format: inform once, don't nudge (see header note).
    if (liquidCalls.length > 0 && !liquidNotified) {
      liquidNotified = true;
      const names = liquidCalls.map((c) => c.name).join(", ");
      harnessIntervention(
        ctx,
        `the model emitted ${liquidCalls.length} Pythonic tool call(s) as text [${names}] (LFM2/Liquid format). ` +
          `little-coder can't execute these directly — serve llama.cpp with \`--jinja\` and the model's MATCHING ` +
          `chat template (not the GGUF's embedded one) so tool calls parse into native tool_calls. ` +
          `See README troubleshooting / issue #42.`,
      );
    }

    // Fenced / <tool_call> / bare-JSON formats: nudge the model back to native
    // tool calling (it has a native channel; this format was a slip).
    if (otherCalls.length > 0) {
      const names = otherCalls.map((c) => c.name).join(", ");
      harnessIntervention(
        ctx,
        `the model wrote ${otherCalls.length} tool call(s) as text [${names}] — nudging it back to native tool calls.`,
      );
      pi.sendUserMessage(
        "Your previous response embedded tool calls inside text (e.g. fenced ```tool blocks, <tool_call> tags, or bare JSON). " +
          "Please re-issue them as NATIVE tool calls. If the intended calls were: " +
          otherCalls.map((c) => `${c.name}(${JSON.stringify(c.input)})`).join("; ") +
          " — please execute them now using your tool-call channel, not text.",
        { deliverAs: "followUp" },
      );
    }
  });
}
