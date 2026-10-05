import { describe, expect, it } from "vitest";

import {
  DEFAULT_CRON_STATE,
  DEFAULT_DAILY_CRON,
  buildCron,
  parseCron,
  reconcileBuilderState,
  type CronBuilderState,
  type CronFrequency,
} from "@/components/form/cronBuilder";

describe("buildCron", () => {
  it("defaults to daily 02:00", () => {
    expect(buildCron(DEFAULT_CRON_STATE)).toBe(DEFAULT_DAILY_CRON);
    expect(DEFAULT_DAILY_CRON).toBe("0 2 * * *");
  });

  it("emits each frequency", () => {
    expect(
      buildCron({ ...DEFAULT_CRON_STATE, frequency: "minutes", everyMinutes: 15 }),
    ).toBe("*/15 * * * *");
    expect(
      buildCron({
        ...DEFAULT_CRON_STATE,
        frequency: "hours",
        everyHours: 1,
        minute: 5,
      }),
    ).toBe("5 * * * *");
    expect(
      buildCron({
        ...DEFAULT_CRON_STATE,
        frequency: "hours",
        everyHours: 6,
        minute: 15,
      }),
    ).toBe("15 */6 * * *");
    expect(
      buildCron({
        ...DEFAULT_CRON_STATE,
        frequency: "weekly",
        hour: 9,
        minute: 30,
        weekdays: [3, 1],
      }),
    ).toBe("30 9 * * 1,3");
    expect(
      buildCron({
        ...DEFAULT_CRON_STATE,
        frequency: "monthly",
        hour: 8,
        minute: 0,
        dayOfMonth: 31,
      }),
    ).toBe("0 8 31 * *");
  });
});

describe("parseCron", () => {
  it("round-trips builder expressions", () => {
    const expressions = [
      "*/5 * * * *",
      "*/10 * * * *",
      "*/15 * * * *",
      "*/20 * * * *",
      "*/30 * * * *",
      "0 * * * *",
      "15 */2 * * *",
      "0 */12 * * *",
      "30 2 * * *",
      "0 2 * * 1",
      "30 9 * * 1,3",
      "0 8 31 * *",
      "15 4 1 * *",
    ];
    for (const expr of expressions) {
      const parsed = parseCron(expr);
      expect(parsed, expr).not.toBeNull();
      expect(buildCron(parsed!)).toBe(expr);
    }
  });

  it("normalizes weekday 7, duplicate days, and list order", () => {
    expect(buildCron(parseCron("0 2 * * 7")!)).toBe("0 2 * * 0");
    expect(buildCron(parseCron("0 2 * * 0,7")!)).toBe("0 2 * * 0");
    expect(buildCron(parseCron("0 2 * * 3,1")!)).toBe("0 2 * * 1,3");
    expect(buildCron(parseCron("0 2 * * 1,1,3")!)).toBe("0 2 * * 1,3");
    expect(parseCron("0 2 * * 3,1")!.weekdays).toEqual([1, 3]);
  });

  it("normalizes an hourly step of 1 to a star", () => {
    expect(buildCron(parseCron("15 */1 * * *")!)).toBe("15 * * * *");
  });

  it("ignores extra whitespace", () => {
    expect(buildCron(parseCron("  0   2   *   *   *  ")!)).toBe("0 2 * * *");
  });

  it("returns null when the builder cannot represent the expression", () => {
    const unrepresentable = [
      "0 2 1 * 1",
      "0 2 1,15 * *",
      "30 1,13 * * *",
      "0 2 * 2 *",
      "0 2 * * 1-5",
      "*/1 * * * *",
      "*/2 * * * *",
      "0 */5 * * *",
      "* * * * *",
      "0 0 29 2 *",
      "not a cron",
      "0 2 * *",
    ];
    for (const expr of unrepresentable) {
      expect(parseCron(expr), expr).toBeNull();
    }
  });
});

function switchFrequency(
  state: CronBuilderState,
  frequency: CronFrequency,
): CronBuilderState {
  const next = { ...state, frequency };
  const reconciled = reconcileBuilderState(next, buildCron(next));
  expect(reconciled).not.toBeNull();
  return reconciled!;
}

describe("reconcileBuilderState", () => {
  it("keeps clock time across minute and hour frequencies", () => {
    let state = parseCron("30 9 * * *")!;
    state = switchFrequency(state, "minutes");
    expect(buildCron(state)).toBe("*/5 * * * *");
    state = switchFrequency(state, "daily");
    expect(buildCron(state)).toBe("30 9 * * *");

    state = parseCron("30 9 * * *")!;
    state = switchFrequency(state, "hours");
    expect(buildCron(state)).toBe("30 * * * *");
    state = switchFrequency(state, "daily");
    expect(buildCron(state)).toBe("30 9 * * *");
  });

  it("keeps weekdays, month day, and steps when the frequency returns", () => {
    let weekly = parseCron("0 2 * * 1,3")!;
    weekly = switchFrequency(weekly, "daily");
    expect(buildCron(weekly)).toBe("0 2 * * *");
    weekly = switchFrequency(weekly, "weekly");
    expect(buildCron(weekly)).toBe("0 2 * * 1,3");

    let monthly = parseCron("0 8 15 * *")!;
    monthly = switchFrequency(monthly, "daily");
    monthly = switchFrequency(monthly, "monthly");
    expect(buildCron(monthly)).toBe("0 8 15 * *");

    let minutes = parseCron("*/15 * * * *")!;
    minutes = switchFrequency(minutes, "daily");
    minutes = switchFrequency(minutes, "minutes");
    expect(buildCron(minutes)).toBe("*/15 * * * *");

    let hours = parseCron("0 */6 * * *")!;
    hours = switchFrequency(hours, "daily");
    hours = switchFrequency(hours, "hours");
    expect(buildCron(hours)).toBe("0 */6 * * *");
  });

  it("returns the parsed value when the external expression differs", () => {
    const held = parseCron("30 9 * * 1,3")!;
    const next = reconcileBuilderState(held, "0 5 * * *");
    expect(next).not.toBe(held);
    expect(buildCron(next!)).toBe("0 5 * * *");
    expect(next!.hour).toBe(5);
    expect(next!.minute).toBe(0);
    expect(next!.weekdays).toEqual([1]);
  });

  it("returns held when the expression still matches", () => {
    const held: CronBuilderState = {
      ...parseCron("30 9 * * *")!,
      weekdays: [1, 3],
      dayOfMonth: 15,
      everyMinutes: 15,
    };
    expect(reconcileBuilderState(held, "30 9 * * *")).toBe(held);
  });

  it("returns null when the expression is not a builder expression", () => {
    expect(reconcileBuilderState(DEFAULT_CRON_STATE, "0 2 1 * 1")).toBeNull();
  });
});
