export const ENTITY_DETAIL_TABS = [
  "overview",
  "attributes",
  "versions",
] as const;

export type EntityDetailTab = (typeof ENTITY_DETAIL_TABS)[number];

export function parseEntityDetailTab(raw: string | null): EntityDetailTab {
  if (raw === "attributes" || raw === "versions" || raw === "overview") {
    return raw;
  }
  return "overview";
}

export function isEntityDetailTab(raw: string | null): raw is EntityDetailTab {
  return raw === "overview" || raw === "attributes" || raw === "versions";
}

export function entityDetailHref(
  entityId: string,
  tab: EntityDetailTab = "overview",
): string {
  if (tab === "overview") {
    return `/console/entities/${entityId}`;
  }
  return `/console/entities/${entityId}?tab=${tab}`;
}

export function entityCreateHref(tab: EntityDetailTab = "overview"): string {
  if (tab === "overview") {
    return "/console/entities/new";
  }
  return `/console/entities/new?tab=${tab}`;
}

export function entityEditHref(
  entityId: string,
  tab: EntityDetailTab = "overview",
): string {
  if (tab === "overview") {
    return `/console/entities/${entityId}/edit`;
  }
  return `/console/entities/${entityId}/edit?tab=${tab}`;
}

export function entityRecordHref(
  mode: "create" | "show" | "edit",
  entityId: string | undefined,
  tab: EntityDetailTab = "overview",
): string {
  if (mode === "create") {
    return entityCreateHref(tab);
  }
  if (!entityId) {
    return "/console/entities";
  }
  if (mode === "edit") {
    return entityEditHref(entityId, tab);
  }
  return entityDetailHref(entityId, tab);
}

const IDENTITY_ERROR_KEYS = new Set(["table_name", "name", "description"]);

export function createFormErrorTab(
  errors: Record<string, unknown>,
): EntityDetailTab {
  for (const key of Object.keys(errors)) {
    if (!errors[key]) continue;
    if (IDENTITY_ERROR_KEYS.has(key)) {
      return "overview";
    }
  }
  for (const key of Object.keys(errors)) {
    if (!errors[key]) continue;
    if (key === "attributes" || key.startsWith("attributes.")) {
      return "attributes";
    }
  }
  return "overview";
}

export function replaceEntityLocation(href: string): void {
  window.history.replaceState(window.history.state, "", href);
}

