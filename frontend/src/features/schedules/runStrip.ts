import type { ScheduleRecentJob } from "@/features/schedules/types";

export const RUN_STRIP_SLOTS = 20;
/** Fraction of the strip height used by the shortest visible bar. */
export const RUN_BAR_MIN_RATIO = 0.2;

/** Pad to a fixed number of slots: empty slots on the left, oldest-to-newest after. */
export function buildRunSlots(
  jobs: readonly ScheduleRecentJob[],
  slots: number = RUN_STRIP_SLOTS,
): (ScheduleRecentJob | null)[] {
  const tail = jobs.slice(-slots);
  const padding: null[] = Array.from({ length: slots - tail.length }, () => null);
  return [...padding, ...tail];
}

/**
 * Bar height as a fraction of the strip in [RUN_BAR_MIN_RATIO, 1].
 * Log scale against the longest run in the strip; unknown duration is the minimum.
 */
export function barHeightRatio(
  durationMs: number | null,
  maxMs: number,
): number {
  if (durationMs === null || maxMs <= 0) return RUN_BAR_MIN_RATIO;
  const scaled = Math.log1p(durationMs) / Math.log1p(maxMs);
  return RUN_BAR_MIN_RATIO + (1 - RUN_BAR_MIN_RATIO) * scaled;
}
