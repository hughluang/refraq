/** Foundation Console Module ids — typed call-site constants, not a second catalog. */
export const ModuleId = {
  dashboard: "dashboard",
  users: "users",
  roles: "roles",
  tokens: "tokens",
  sources: "sources",
  catalog: "catalog",
  jobs: "jobs",
  settings: "settings",
} as const;

export type ModuleIdName = (typeof ModuleId)[keyof typeof ModuleId];

/** Refine UX actions mirrored from Console Module Identity. */
export const ModuleAction = {
  list: "list",
  create: "create",
  edit: "edit",
  delete: "delete",
  show: "show",
} as const;

export type ModuleActionName = (typeof ModuleAction)[keyof typeof ModuleAction];
