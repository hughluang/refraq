import type { Instant } from "@/lib/instant";

/** Wall-time text: picker `YYYY-MM-DD HH:mm:ss` or datetime-local `YYYY-MM-DDTHH:mm`. */
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

/** Instant → wall time in `zone`. Null or absent → null. */
export function instantToWall(
  value: Instant | null | undefined,
  zone: string,
  separator: " " | "T" = " ",
): string | null {
  if (!value) return null;
  const p = wallPartsAt(value.epochMs(), zone);
  return `${p.year}-${pad(p.month)}-${pad(p.day)}${separator}${pad(p.hour)}:${pad(p.minute)}:${pad(p.second)}`;
}

/**
 * Wall time in `zone` → UTC Instant for the API. Empty or unparseable → null.
 * A wall time skipped by a DST gap resolves forward by the gap length.
 */
export function wallToInstant(
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
  // Wall arithmetic stays on whole seconds, so `toISOString` ends in `.000Z`.
  const text = new Date(resolved).toISOString();
  return `${text.slice(0, -5)}Z`;
}
