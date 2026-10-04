/** IANA zone the browser uses when Display Timezone is unset. Null when it cannot be read. */
export function browserTimeZone(): string | null {
  try {
    const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
    return zone ? zone : null;
  } catch {
    return null;
  }
}

/** Zone named once on the schedule next-run column. Empty preference follows the browser. */
export function displayZoneId(
  preference: string | null | undefined,
): string | null {
  const zone = preference?.trim();
  if (zone) return zone;
  return browserTimeZone();
}

export type FormatInstantOptions = {
  /** IANA zone; null/undefined = browser default. */
  timeZone?: string | null;
  /** Historical spellings of `timeZone`, tried in order when the browser rejects the current id. */
  aliases?: readonly string[];
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
  const locale = options?.locale;
  const timeZone = options?.timeZone || undefined;
  if (!timeZone) {
    return date.toLocaleString(locale);
  }
  for (const zone of [timeZone, ...(options?.aliases ?? [])]) {
    try {
      return date.toLocaleString(locale, { timeZone: zone });
    } catch {
      continue;
    }
  }
  return `${date.toLocaleString(locale, { timeZone: "UTC" })} UTC`;
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
 * Job run time in ms. Finished jobs use `finished_at - started_at`; running jobs
 * use `now - started_at`. Null when not started, unparsable, negative, or not
 * running without a finish.
 */
export function runDurationMs(job: JobDurationFields, now: number): number | null {
  if (!job.started_at) return null;
  const start = Date.parse(job.started_at);
  if (Number.isNaN(start)) return null;
  let ms: number;
  if (job.finished_at) {
    ms = Date.parse(job.finished_at) - start;
  } else if (job.status === "running") {
    ms = now - start;
  } else {
    return null;
  }
  return Number.isFinite(ms) && ms >= 0 ? ms : null;
}

/** Job run duration text; queued / no start → "—". */
export function formatJobDuration(
  job: JobDurationFields,
  now: Date = new Date(),
): string {
  const ms = runDurationMs(job, now.getTime());
  return ms === null ? "—" : formatDurationMs(ms);
}
