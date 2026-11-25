export const SETUP_STEPS = ["source", "transport", "target", "gateway", "config", "runtime", "verify"] as const;

export type SetupStep = typeof SETUP_STEPS[number];

const READINESS_STEP: Record<string, SetupStep> = {
  capture_admission: "runtime",
  table_unqualified: "config",
  mirror_permission_blocked: "source",
  mirror_schema_blocked: "source",
  mirror_continuity_blocked: "gateway",
  incremental_snapshot_blocked: "gateway",
};

export function setupStepForReadiness(key: string): SetupStep | null {
  return READINESS_STEP[key] ?? null;
}

export function setupHref(sourceId?: string | null, step?: string | null) {
  const query = new URLSearchParams();
  if (sourceId) query.set("source_id", sourceId);
  if (step) query.set("step", step);
  const text = query.toString();
  return `/console/mirrors/setup${text ? `?${text}` : ""}`;
}
