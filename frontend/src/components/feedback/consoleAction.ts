import type { ApplyApiErrorResult } from "@/components/form/useConsoleForm";

export type ActionSafety = "confirm" | "undoable" | "immediate";

type NamedAction = {
  /** Operator-facing name of the record the verb acts on. */
  recordName: string;
};

/**
 * Safety class is a required discriminant.
 * An object without `safety` matches none of the branches and does not compile.
 */
export type ConsoleAction =
  | (NamedAction & {
      safety: "confirm";
      /** What the verb will do. The dialog also says it cannot be undone. */
      consequence: string;
      title?: string;
      confirmLabel?: string;
      confirmColor?: string;
    })
  | (NamedAction & {
      safety: "undoable";
      undo: () => Promise<unknown>;
    })
  | (NamedAction & {
      safety: "immediate";
    });

export type ConsoleMutation = ConsoleAction & {
  /** Localized outcome phrase. The success title pairs it with the record name. */
  outcome: string;
  execute: () => Promise<unknown>;
  /** Refresh the list or record after the verb, and again after a successful undo. */
  onSuccess?: () => void | Promise<void>;
  /**
   * When set, field and form errors stay on the form frame
   * (`saveFailureFrom` / `FormErrorSummary`) instead of an error notification.
   */
  applyApiError?: (error: unknown) => ApplyApiErrorResult;
  /** Identifies the triggering control when one hook serves several. */
  key?: string;
};
