/** 2922 days (8 * 365.25). Same ceiling as the backend cadence horizon. */
export const MAX_CADENCE_SECONDS = 2922 * 86400;

export const INTERVAL_UNITS = ["seconds", "minutes", "hours", "days"] as const;

export type IntervalUnit = (typeof INTERVAL_UNITS)[number];

const UNIT_SECONDS: Record<IntervalUnit, number> = {
  seconds: 1,
  minutes: 60,
  hours: 3600,
  days: 86400,
};

const LARGEST_FIRST: IntervalUnit[] = ["days", "hours", "minutes", "seconds"];

/** Largest unit that divides `seconds` evenly. 7200 → 2 hours, 90 → 90 seconds. */
export function splitIntervalSeconds(seconds: number): {
  amount: number;
  unit: IntervalUnit;
} {
  const whole = Math.trunc(seconds);
  for (const unit of LARGEST_FIRST) {
    const size = UNIT_SECONDS[unit];
    if (whole >= size && whole % size === 0) {
      return { amount: whole / size, unit };
    }
  }
  return { amount: whole, unit: "seconds" };
}

export function intervalToSeconds(amount: number, unit: IntervalUnit): number {
  return amount * UNIT_SECONDS[unit];
}

export function isPositiveInteger(value: number | string): boolean {
  if (typeof value === "number") {
    return Number.isInteger(value) && value >= 1;
  }
  if (!/^\d+$/.test(value.trim())) return false;
  const parsed = Number(value);
  return Number.isInteger(parsed) && parsed >= 1;
}

/** Positive amount whose unit conversion stays within the cadence horizon. */
export function isAllowedInterval(
  amount: number | string,
  unit: IntervalUnit,
): boolean {
  if (!isPositiveInteger(amount)) return false;
  const seconds = intervalToSeconds(Number(amount), unit);
  return Number.isSafeInteger(seconds) && seconds <= MAX_CADENCE_SECONDS;
}
