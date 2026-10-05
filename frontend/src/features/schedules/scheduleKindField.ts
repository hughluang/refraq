export type SourceScheduleKind = "structure" | "join_detection";

export function scheduleKindFromTask(
  workKind: string | null | undefined,
): SourceScheduleKind {
  return workKind === "join_detection" ? "join_detection" : "structure";
}
