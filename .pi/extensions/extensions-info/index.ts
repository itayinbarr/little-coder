import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { terminalColumns } from "../_shared/width.ts";
import { panelLines, parseManifest } from "./manifest.ts";

// `/extensions` — what is loaded, where it came from, and what failed.
//
// Two problems this solves, both surfaced in the #67/#69 threads:
//
// 1. Discoverability. little-coder loads a fixed bundled set and nothing else
//    unless you opt in, but there was no way to SEE that from inside the TUI —
//    people reasonably assumed their pi extensions were loading and quietly
//    weren't. We force `quietStartup` to keep launch clean, which also hides
//    pi's own inventory dump, leaving `--verbose` as the only window.
//
// 2. Silent failures. A user extension that doesn't resolve warns once on
//    stderr, moments before the TUI paints over it. Those warnings now also
//    fire as a notification at session start and stay visible in this panel.
//
// The launcher is the only component that knows the provenance of each path —
// pi just receives a flat list of `--extension` flags — so it serializes an
// inventory into LITTLE_CODER_EXTENSION_MANIFEST and this reads it back.
//
// It renders as a toggling widget rather than a transcript message on purpose:
// a custom message would be converted to a user-role message and sent to the
// model (core/messages.js::convertToLlm), spending context on a diagnostic the
// model has no use for.

const WIDGET_KEY = "extensions-info";

let panelOn = false;

function setPanel(ctx: any, on: boolean): void {
  if (!ctx?.hasUI) return;
  const content = on
    ? panelLines(parseManifest(process.env.LITTLE_CODER_EXTENSION_MANIFEST), terminalColumns())
    : undefined;
  ctx.ui.setWidget(WIDGET_KEY, content, { placement: "belowEditor" });
}

export default function (pi: ExtensionAPI) {
  pi.registerCommand("extensions", {
    description: "Show loaded extensions, where each came from, and any load errors",
    handler: async (_args: string, ctx: any) => {
      panelOn = !panelOn;
      setPanel(ctx, panelOn);
    },
  });

  pi.on("session_start", async (_event, ctx) => {
    // Default hidden so a resumed session doesn't surface a stale panel.
    panelOn = false;
    setPanel(ctx, false);

    // Surface load failures unprompted — the launcher's stderr warning has
    // already been painted over by the time the user can read anything.
    const { warnings } = parseManifest(process.env.LITTLE_CODER_EXTENSION_MANIFEST);
    if (!ctx.hasUI) return;
    for (const w of warnings) {
      ctx.ui.notify(`extensions: ${w.replace(/^little-coder:\s*/, "")}`, "warning");
    }
  });
}
