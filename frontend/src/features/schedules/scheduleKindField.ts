export type SourceScheduleKind = "structure" | "join_detection";

export function defaultCron(kind: SourceScheduleKind): string {
  return kind === "join_detection" ? "0 4 * * *" : "0 2 * * *";
}

export function scheduleKindFromTask(
  workKind: string | null | undefined,
): SourceScheduleKind {
  return workKind === "join_detection" ? "join_detection" : "structure";
}

/** i18n key for the "daily" cadence option label for this work kind. */
export function dailyPresetLabelKey(kind: SourceScheduleKind): string {
  return kind === "join_detection"
    ? "schedules.preset.dailyJoinDetection"
    : "schedules.preset.dailyStructure";
}

export function isDailyCron(
  cron: string | null | undefined,
  kind: SourceScheduleKind,
): boolean {
  return cron === defaultCron(kind);
}
