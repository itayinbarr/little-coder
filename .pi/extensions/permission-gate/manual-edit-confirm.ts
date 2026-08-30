// Manual-mode confirmation for write/edit tools (apply/deny/apply-all).

export type EditDecision = "apply" | "deny" | "apply-all";

const EDIT_OPTIONS = ["Apply", "Deny", "Apply all (this session)"] as const;

export interface EditConfirmer {
  confirm(ctx: any, toolName: string, input: any): Promise<EditDecision>;
}

/** Create a fresh confirmer for one session. Headless (no select) denies by default. */
export function createEditConfirmer(): EditConfirmer {
  let allowAll = false;

  return {
    async confirm(ctx: any, toolName: string, input: any): Promise<EditDecision> {
      if (allowAll) return "apply";
      const select = ctx?.ui?.select;
      if (typeof select !== "function") return "deny";
      const target =
        typeof input?.path === "string"
          ? input.path
          : typeof input?.file_path === "string"
            ? input.file_path
            : "(unknown path)";
      const choice = await select(
        `About to ${toolName} ${target}. Apply this change?`,
        [...EDIT_OPTIONS],
      );
      if (choice === "Apply all (this session)") {
        allowAll = true;
        return "apply-all";
      }
      if (choice === "Apply") return "apply";
      return "deny";
    },
  };
}
