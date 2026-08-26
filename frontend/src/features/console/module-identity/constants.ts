/** Refine UX actions mirrored from Console Module Identity. */
export const ModuleAction = {
  list: "list",
  create: "create",
  edit: "edit",
  delete: "delete",
  show: "show",
  sample: "sample",
} as const;

export type ModuleActionName = (typeof ModuleAction)[keyof typeof ModuleAction];
