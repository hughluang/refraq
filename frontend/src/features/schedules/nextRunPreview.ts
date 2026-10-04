import type { ScheduledTask } from "@/features/schedules/types";

export type CadenceKind = "hourly" | "daily" | "weekly" | "custom" | "interval";

export type CadenceDraft = {
  cadence: CadenceKind;
  cron: string;
  interval_seconds: number | string;
};

export type NextRunPreview = "hidden" | "saved" | "recalculates";

type SavedCadence = Pick<ScheduledTask, "cron" | "interval_seconds">;

/** Whether the draft still commits the same cadence the saved row already has. */
export function savedCadenceMatches(
  schedule: SavedCadence,
  draft: CadenceDraft,
): boolean {
  if (schedule.interval_seconds != null) {
    if (draft.cadence !== "interval") return false;
    const seconds = Number(draft.interval_seconds);
    return Number.isFinite(seconds) && seconds === schedule.interval_seconds;
  }
  if (draft.cadence === "interval") return false;
  return draft.cron.trim() === (schedule.cron ?? "").trim();
}

/**
 * Saved row whose cadence is unchanged shows that row's next run.
 * A changed cadence must not invent a clock; create has nothing saved.
 */
export function nextRunPreview(
  schedule: SavedCadence | null | undefined,
  draft: CadenceDraft,
): NextRunPreview {
  if (!schedule) return "hidden";
  return savedCadenceMatches(schedule, draft) ? "saved" : "recalculates";
}

/** Same string the schedule list uses for the next-run cell. */
export function formatScheduleNextRun(
  task: { enabled: boolean; next_run_at: string | null },
  formatInstant: (value: string | null | undefined) => string,
  pausedLabel: string,
): string {
  if (!task.enabled) return pausedLabel;
  if (task.next_run_at) return formatInstant(task.next_run_at);
  return "—";
}
