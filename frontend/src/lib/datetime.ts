import { Instant } from "@/lib/instant";

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

function acceptsZone(zone: string): boolean {
  try {
    new Intl.DateTimeFormat("en-US", { timeZone: zone });
    return true;
  } catch {
    return false;
  }
}

/**
 * Zone that formats an Instant and interprets a typed wall time.
 * A named preference is used when the browser accepts it, then the first
 * accepted alias, then UTC. An empty preference follows the browser, or UTC
 * when that zone cannot be read.
 */
export function resolveDisplayZone(
  preference: string | null | undefined,
  aliases: readonly string[] = [],
): string {
  const named = preference?.trim() ?? "";
  if (!named) return browserTimeZone() ?? "UTC";
  for (const candidate of [named, ...aliases]) {
    if (acceptsZone(candidate)) return candidate;
  }
  return "UTC";
}

/** Received text is not a platform Instant. Display catches this locally. */
export class UnreadableInstantError extends Error {
  constructor(value: string) {
    super(`invalid Instant: ${value}`);
    this.name = "UnreadableInstantError";
  }
}

function dateFromReceivedInstant(value: string): Date {
  let instant: Instant;
  try {
    instant = Instant.parse(value);
  } catch {
    throw new UnreadableInstantError(value);
  }
  return new Date(instant.epochMs());
}

export type FormatInstantOptions = {
  /** IANA zone; null/undefined = browser default. */
  timeZone?: string | null;
  /** Historical spellings of `timeZone`, tried in order when the browser rejects the current id. */
  aliases?: readonly string[];
  locale?: string;
};

/**
 * Human-friendly instant for list/detail UI.
 * A string is the received platform Instant text. It is parsed once and formatted;
 * it is not rewritten with `Date#toISOString` (that would turn seconds into `.000Z`).
 */
export function formatInstant(
  value: Instant | string | null | undefined,
  options?: FormatInstantOptions,
): string {
  if (!value) {
    return "—";
  }
  const date =
    typeof value === "string"
      ? dateFromReceivedInstant(value)
      : new Date(value.epochMs());
  const locale = options?.locale;
  const named = options?.timeZone?.trim() ?? "";
  const aliases = options?.aliases ?? [];
  const zone = resolveDisplayZone(named || null, aliases);
  if (!named) {
    if (browserTimeZone()) return date.toLocaleString(locale);
    return date.toLocaleString(locale, { timeZone: "UTC" });
  }
  const text = date.toLocaleString(locale, { timeZone: zone });
  const accepted = [named, ...aliases].some((candidate) => acceptsZone(candidate));
  if (!accepted) return `${text} UTC`;
  return text;
}

type JobDurationFields = {
  status: string;
  started_at: Instant | null;
  finished_at: Instant | null;
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
 * use `now - started_at`. Null when not started, negative, or not running
 * without a finish.
 */
export function runDurationMs(job: JobDurationFields, now: number): number | null {
  if (!job.started_at) return null;
  const start = job.started_at.epochMs();
  let ms: number;
  if (job.finished_at) {
    ms = job.finished_at.epochMs() - start;
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
