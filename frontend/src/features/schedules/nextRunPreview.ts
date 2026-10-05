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
