export const MINUTE_STEPS = [5, 10, 15, 20, 30] as const;
export const HOUR_STEPS = [1, 2, 3, 4, 6, 8, 12] as const;

export type MinuteStep = (typeof MINUTE_STEPS)[number];
export type HourStep = (typeof HOUR_STEPS)[number];
export type CronFrequency = "minutes" | "hours" | "daily" | "weekly" | "monthly";

export type CronBuilderState = {
  frequency: CronFrequency;
  everyMinutes: MinuteStep;
  everyHours: HourStep;
  minute: number;
  hour: number;
  /** Cron weekdays, Sunday = 0. Order is normalized ascending. */
  weekdays: number[];
  dayOfMonth: number;
};

export const DEFAULT_CRON_STATE: CronBuilderState = {
  frequency: "daily",
  everyMinutes: 5,
  everyHours: 1,
  minute: 0,
  hour: 2,
  weekdays: [1],
  dayOfMonth: 1,
};

export const DEFAULT_DAILY_CRON = "0 2 * * *";

function isMinuteStep(value: number): value is MinuteStep {
  return (MINUTE_STEPS as readonly number[]).includes(value);
}

function isHourStep(value: number): value is HourStep {
  return (HOUR_STEPS as readonly number[]).includes(value);
}

function parseSingle(token: string, min: number, max: number): number | null {
  if (!/^\d+$/.test(token)) return null;
  const value = Number(token);
  if (!Number.isInteger(value) || value < min || value > max) return null;
  return value;
}

function parseEveryStep(token: string): number | null {
  const match = /^\*\/(\d+)$/.exec(token);
  if (!match) return null;
  const step = Number(match[1]);
  if (!Number.isInteger(step) || step < 1) return null;
  return step;
}

function parseDowList(token: string): number[] | null {
  if (token.includes("/") || token.includes("-") || token.includes("*")) return null;
  const days = new Set<number>();
  for (const part of token.split(",")) {
    const value = parseSingle(part, 0, 7);
    if (value == null) return null;
    days.add(value === 7 ? 0 : value);
  }
  if (days.size === 0) return null;
  return [...days].sort((left, right) => left - right);
}

/** Turn builder state into a five-field cron expression. */
export function buildCron(state: CronBuilderState): string {
  const { minute, hour } = state;
  switch (state.frequency) {
    case "minutes":
      return `*/${state.everyMinutes} * * * *`;
    case "hours":
      return state.everyHours === 1
        ? `${minute} * * * *`
        : `${minute} */${state.everyHours} * * *`;
    case "daily":
      return `${minute} ${hour} * * *`;
    case "weekly": {
      const days = [...state.weekdays].sort((left, right) => left - right);
      return `${minute} ${hour} * * ${days.join(",")}`;
    }
    case "monthly":
      return `${minute} ${hour} ${state.dayOfMonth} * *`;
  }
}

/**
 * Parse an expression the builder can show.
 * Weekday 7 and 0 are both Sunday. List order does not matter.
 * Returns null when the expression needs the raw cron field.
 */
export function parseCron(expr: string): CronBuilderState | null {
  const parts = expr.trim().split(/\s+/);
  if (parts.length !== 5) return null;
  const [minute, hour, dom, month, dow] = parts;
  if (month !== "*") return null;

  if (hour === "*" && dom === "*" && dow === "*") {
    const step = parseEveryStep(minute);
    if (step != null && isMinuteStep(step)) {
      return {
        ...DEFAULT_CRON_STATE,
        frequency: "minutes",
        everyMinutes: step,
      };
    }
  }

  if (dom === "*" && dow === "*") {
    const atMinute = parseSingle(minute, 0, 59);
    if (atMinute == null) return null;
    if (hour === "*") {
      return {
        ...DEFAULT_CRON_STATE,
        frequency: "hours",
        everyHours: 1,
        minute: atMinute,
      };
    }
    const hourStep = parseEveryStep(hour);
    if (hourStep != null) {
      if (!isHourStep(hourStep)) return null;
      return {
        ...DEFAULT_CRON_STATE,
        frequency: "hours",
        everyHours: hourStep,
        minute: atMinute,
      };
    }
    const atHour = parseSingle(hour, 0, 23);
    if (atHour == null) return null;
    return {
      ...DEFAULT_CRON_STATE,
      frequency: "daily",
      hour: atHour,
      minute: atMinute,
    };
  }

  if (dom === "*" && dow !== "*") {
    const atMinute = parseSingle(minute, 0, 59);
    const atHour = parseSingle(hour, 0, 23);
    const weekdays = parseDowList(dow);
    if (atMinute == null || atHour == null || weekdays == null) return null;
    return {
      ...DEFAULT_CRON_STATE,
      frequency: "weekly",
      hour: atHour,
      minute: atMinute,
      weekdays,
    };
  }

  if (dow === "*" && dom !== "*") {
    const atMinute = parseSingle(minute, 0, 59);
    const atHour = parseSingle(hour, 0, 23);
    const day = parseSingle(dom, 1, 31);
    if (atMinute == null || atHour == null || day == null) return null;
    return {
      ...DEFAULT_CRON_STATE,
      frequency: "monthly",
      hour: atHour,
      minute: atMinute,
      dayOfMonth: day,
    };
  }

  return null;
}

/**
 * Keep builder fields that the current expression does not encode.
 * An external expression that builds differently replaces the held state.
 */
export function reconcileBuilderState(
  held: CronBuilderState,
  value: string,
): CronBuilderState | null {
  const parsed = parseCron(value);
  if (parsed != null && buildCron(held) === buildCron(parsed)) {
    return held;
  }
  return parsed;
}
