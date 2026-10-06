import {
  splitIntervalSeconds,
  type IntervalUnit,
} from "@/features/schedules/intervalUnits";

export type CronTranslate = (
  key: string,
  options?: Record<string, string | number>,
) => string;

const MAX_TIMES = 4;
const P = "schedules.cadence.phrase";

type Bounds = { min: number; max: number };

function expandToken(token: string, { min, max }: Bounds): number[] | null {
  const [base, stepText, extra] = token.split("/");
  if (extra !== undefined) return null;
  let step = 1;
  if (stepText !== undefined) {
    if (!/^\d+$/.test(stepText) || Number(stepText) < 1) return null;
    step = Number(stepText);
  }
  let from: number;
  let to: number;
  if (base === "*") {
    from = min;
    to = max;
  } else if (/^\d+$/.test(base)) {
    from = Number(base);
    to = stepText !== undefined ? max : from;
  } else {
    const m = /^(\d+)-(\d+)$/.exec(base);
    if (!m) return null;
    from = Number(m[1]);
    to = Number(m[2]);
  }
  if (from < min || to > max || from > to) return null;
  const out: number[] = [];
  for (let v = from; v <= to; v += step) out.push(v);
  return out;
}

function expandField(field: string, bounds: Bounds): number[] | null {
  const set = new Set<number>();
  for (const token of field.split(",")) {
    const values = expandToken(token, bounds);
    if (!values) return null;
    values.forEach((v) => set.add(v));
  }
  return [...set].sort((a, b) => a - b);
}

function isStar(field: string): boolean {
  return field === "*" || field === "*/1";
}

function starStep(field: string): number | null {
  const m = /^\*\/(\d+)$/.exec(field);
  return m ? Number(m[1]) : null;
}

function pad(n: number): string {
  return String(n).padStart(2, "0");
}

function sundayFirst(locale: string): boolean {
  return locale.toLowerCase().startsWith("en-us");
}

function dateName(
  locale: string,
  options: Intl.DateTimeFormatOptions,
  date: Date,
): string {
  return new Intl.DateTimeFormat(locale, { ...options, timeZone: "UTC" }).format(
    date,
  );
}

/** Groups runs of 3+ consecutive positions into "a to c"; shorter runs are listed. */
function joinRuns(
  positions: number[],
  label: (position: number) => string,
  t: CronTranslate,
): string {
  const parts: string[] = [];
  let i = 0;
  while (i < positions.length) {
    let j = i;
    while (j + 1 < positions.length && positions[j + 1] === positions[j] + 1) {
      j += 1;
    }
    if (j - i >= 2) {
      parts.push(`${label(positions[i])}${t(`${P}.to`)}${label(positions[j])}`);
    } else {
      for (let k = i; k <= j; k += 1) parts.push(label(positions[k]));
    }
    i = j + 1;
  }
  return parts.join(t(`${P}.sep`));
}

function weekdayText(values: number[], locale: string, t: CronTranslate) {
  const order = sundayFirst(locale)
    ? [0, 1, 2, 3, 4, 5, 6]
    : [1, 2, 3, 4, 5, 6, 0];
  const positions = values.map((v) => order.indexOf(v)).sort((a, b) => a - b);
  return joinRuns(
    positions,
    (p) =>
      // 2024-01-07 is a Sunday.
      dateName(locale, { weekday: "short" }, new Date(Date.UTC(2024, 0, 7 + order[p]))),
    t,
  );
}

function monthText(values: number[], locale: string, t: CronTranslate) {
  return joinRuns(
    values,
    (m) => dateName(locale, { month: "short" }, new Date(Date.UTC(2024, m - 1, 1))),
    t,
  );
}

function dayText(values: number[], t: CronTranslate) {
  return joinRuns(values, (d) => String(d), t);
}

type Scope = { daily: boolean; text: string };

function buildScope(
  dom: string,
  month: string,
  dow: string,
  locale: string,
  t: CronTranslate,
): Scope | null {
  const days = isStar(dom) ? null : expandField(dom, { min: 1, max: 31 });
  const months = isStar(month) ? null : expandField(month, { min: 1, max: 12 });
  let weekdays: number[] | null = null;
  if (!isStar(dow)) {
    const raw = expandField(dow, { min: 0, max: 7 });
    if (!raw) return null;
    weekdays = [...new Set(raw.map((v) => v % 7))].sort((a, b) => a - b);
    if (weekdays.length === 7) weekdays = null;
  }
  if ((!isStar(dom) && !days) || (!isStar(month) && !months)) return null;
  if (days && weekdays) return null;
  if (days && days.length === 31) return scopeOf(null, months, weekdays, locale, t);
  return scopeOf(days, months, weekdays, locale, t);
}

function scopeOf(
  days: number[] | null,
  months: number[] | null,
  weekdays: number[] | null,
  locale: string,
  t: CronTranslate,
): Scope {
  const m = months ? monthText(months, locale, t) : "";
  if (weekdays) {
    const d = weekdayText(weekdays, locale, t);
    return months
      ? { daily: false, text: t(`${P}.scope.monthsWeekly`, { months: m, days: d }) }
      : { daily: false, text: t(`${P}.scope.weekly`, { days: d }) };
  }
  if (days) {
    const d = dayText(days, t);
    return months
      ? { daily: false, text: t(`${P}.scope.yearlyDay`, { months: m, days: d }) }
      : { daily: false, text: t(`${P}.scope.monthly`, { days: d }) };
  }
  return months
    ? { daily: false, text: t(`${P}.scope.months`, { months: m }) }
    : { daily: true, text: t(`${P}.scope.daily`) };
}

function everyText(amount: number, unit: IntervalUnit, t: CronTranslate) {
  return t(`${P}.every`, { amount, unit: t(`${P}.unit.${unit}`, { count: amount }) });
}

function withScope(scope: Scope, body: string, t: CronTranslate) {
  return scope.daily ? body : t(`${P}.scoped`, { scope: scope.text, body });
}

/** Friendly sentence for the cron subset the backend accepts; null when not representable. */
export function describeCronCadence(
  cron: string,
  locale: string,
  t: CronTranslate,
): string | null {
  const fields = cron.trim().split(/\s+/);
  if (fields.length !== 5) return null;
  const [minF, hourF, domF, monF, dowF] = fields;
  const scope = buildScope(domF, monF, dowF, locale, t);
  if (!scope) return null;

  const minuteStep = isStar(minF) ? 1 : starStep(minF);
  if (minuteStep !== null) {
    const every = everyText(minuteStep, "minutes", t);
    if (isStar(hourF)) return withScope(scope, every, t);
    if (starStep(hourF) !== null) return null;
    const hours = expandField(hourF, { min: 0, max: 23 });
    if (!hours || hours[hours.length - 1] - hours[0] + 1 !== hours.length) {
      return null;
    }
    const body = t(`${P}.window`, {
      from: `${pad(hours[0])}:00`,
      to: `${pad(hours[hours.length - 1])}:59`,
      every,
    });
    return withScope(scope, body, t);
  }

  const minutes = expandField(minF, { min: 0, max: 59 });
  if (!minutes) return null;

  if (isStar(hourF)) {
    if (minutes.length !== 1) return null;
    return withScope(scope, t(`${P}.hourlyAt`, { minute: pad(minutes[0]) }), t);
  }
  const hourStep = starStep(hourF);
  if (hourStep !== null) {
    if (minutes.length !== 1) return null;
    const every = everyText(hourStep, "hours", t);
    const body =
      minutes[0] === 0
        ? t(`${P}.onTheHour`, { every })
        : t(`${P}.everyAtMinute`, { every, minute: pad(minutes[0]) });
    return withScope(scope, body, t);
  }

  const hours = expandField(hourF, { min: 0, max: 23 });
  if (!hours || hours.length * minutes.length > MAX_TIMES) return null;
  const times = hours
    .flatMap((h) => minutes.map((m) => `${pad(h)}:${pad(m)}`))
    .join(t(`${P}.sep`));
  return t(`${P}.scoped`, {
    scope: scope.text,
    body: t(`${P}.at`, { times }),
  });
}

export function describeIntervalSeconds(seconds: number, t: CronTranslate) {
  const { amount, unit } = splitIntervalSeconds(seconds);
  return everyText(amount, unit, t);
}
