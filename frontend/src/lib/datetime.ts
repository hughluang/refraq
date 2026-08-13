export type FormatInstantOptions = {
  /** IANA zone; null/undefined = browser default. */
  timeZone?: string | null;
  locale?: string;
};

/** Human-friendly instant for list/detail UI. */
export function formatInstant(
  value: string | null | undefined,
  options?: FormatInstantOptions,
): string {
  if (!value) {
    return "—";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "—";
  }
  const timeZone = options?.timeZone || undefined;
  const locale = options?.locale;
  try {
    return date.toLocaleString(locale, timeZone ? { timeZone } : undefined);
  } catch {
    return "—";
  }
}

type JobDurationFields = {
  status: string;
  started_at: string | null;
  finished_at: string | null;
};

/** Format a non-negative duration in milliseconds. */
export function formatDurationMs(ms: number): string {
  if (ms < 0 || !Number.isFinite(ms)) {
    return "—";
  }
  if (ms < 1000) {
    return `${Math.round(ms)}ms`;
  }
  const totalSeconds = Math.floor(ms / 1000);
  if (totalSeconds < 60) {
    return `${totalSeconds}s`;
  }
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) {
    return seconds > 0 ? `${hours}h ${minutes}m ${seconds}s` : `${hours}h ${minutes}m`;
  }
  return seconds > 0 ? `${minutes}m ${seconds}s` : `${minutes}m`;
}

/**
 * Job run duration from started/finished timestamps.
 * Running jobs use `now - started_at`; queued / no start → "—".
 */
export function formatJobDuration(
  job: JobDurationFields,
  now: Date = new Date(),
): string {
  if (!job.started_at) {
    return "—";
  }
  const start = new Date(job.started_at).getTime();
  if (Number.isNaN(start)) {
    return "—";
  }
  if (job.finished_at) {
    const end = new Date(job.finished_at).getTime();
    if (Number.isNaN(end)) {
      return "—";
    }
    return formatDurationMs(end - start);
  }
  if (job.status === "running") {
    return formatDurationMs(now.getTime() - start);
  }
  return "—";
}
