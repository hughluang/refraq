import { MAX_CADENCE_SECONDS } from "@/features/schedules/intervalUnits";

/** Picker wall-time value shape used by `@mantine/dates` (`YYYY-MM-DD HH:mm:ss`). */
const WALL_PATTERN = /^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?$/;

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

type WallParts = {
  year: number;
  month: number;
  day: number;
  hour: number;
  minute: number;
  second: number;
};

function wallPartsAt(ms: number, zone: string): WallParts {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: zone,
    hourCycle: "h23",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).formatToParts(new Date(ms));
  const pick = (type: Intl.DateTimeFormatPartTypes) =>
    Number(parts.find((part) => part.type === type)?.value ?? "0");
  return {
    year: pick("year"),
    month: pick("month"),
    day: pick("day"),
    hour: pick("hour"),
    minute: pick("minute"),
    second: pick("second"),
  };
}

function wallAsUtcMs(parts: WallParts): number {
  return Date.UTC(
    parts.year,
    parts.month - 1,
    parts.day,
    parts.hour,
    parts.minute,
    parts.second,
  );
}

function zoneOffsetMs(ms: number, zone: string): number {
  return wallAsUtcMs(wallPartsAt(ms, zone)) - Math.floor(ms / 1000) * 1000;
}

/** Empty (start immediately), any past anchor, or a future start within the cadence horizon. */
export function isAllowedStartAt(
  value: string | null,
  now: number = Date.now(),
): boolean {
  if (value === null) return true;
  const ms = Date.parse(value);
  return !Number.isNaN(ms) && ms <= now + MAX_CADENCE_SECONDS * 1000;
}

/** True while a Schedule Start is still ahead; a past one is only the anchor. */
export function startsInFuture(
  value: string | null | undefined,
  now: number = Date.now(),
): boolean {
  if (!value) return false;
  const ms = Date.parse(value);
  return !Number.isNaN(ms) && ms > now;
}

/** API Instant → picker wall time in `zone`. Null/absent/unparsable → null (start immediately). */
export function startAtToWall(
  value: string | null | undefined,
  zone: string,
): string | null {
  if (!value) return null;
  const ms = Date.parse(value);
  if (Number.isNaN(ms)) return null;
  const p = wallPartsAt(ms, zone);
  return `${p.year}-${pad(p.month)}-${pad(p.day)} ${pad(p.hour)}:${pad(p.minute)}:${pad(p.second)}`;
}

/**
 * Picker wall time in `zone` → UTC Instant for the API. Empty → null (start immediately).
 * A wall time skipped by a DST gap resolves forward by the gap length.
 */
export function wallToStartAt(
  wall: string | null | undefined,
  zone: string,
): string | null {
  const match = wall ? WALL_PATTERN.exec(wall.trim()) : null;
  if (!match) return null;
  const guess = wallAsUtcMs({
    year: Number(match[1]),
    month: Number(match[2]),
    day: Number(match[3]),
    hour: Number(match[4]),
    minute: Number(match[5]),
    second: Number(match[6] ?? "0"),
  });
  const first = guess - zoneOffsetMs(guess, zone);
  const second = guess - zoneOffsetMs(first, zone);
  const resolved =
    wallAsUtcMs(wallPartsAt(second, zone)) === guess ? second : first;
  return new Date(resolved).toISOString();
}
