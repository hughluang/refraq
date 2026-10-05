import { describe, expect, it } from "vitest";

import {
  MAX_CADENCE_SECONDS,
  intervalToSeconds,
  isAllowedInterval,
  isPositiveInteger,
  splitIntervalSeconds,
} from "@/features/schedules/intervalUnits";

describe("splitIntervalSeconds", () => {
  it("picks the largest unit that divides evenly", () => {
    expect(splitIntervalSeconds(90)).toEqual({ amount: 90, unit: "seconds" });
    expect(splitIntervalSeconds(7200)).toEqual({ amount: 2, unit: "hours" });
    expect(splitIntervalSeconds(120)).toEqual({ amount: 2, unit: "minutes" });
    expect(splitIntervalSeconds(86400)).toEqual({ amount: 1, unit: "days" });
    expect(splitIntervalSeconds(3600)).toEqual({ amount: 1, unit: "hours" });
  });

  it("converts back to seconds", () => {
    const split = splitIntervalSeconds(7200);
    expect(intervalToSeconds(split.amount, split.unit)).toBe(7200);
    expect(intervalToSeconds(90, "seconds")).toBe(90);
  });
});

describe("isPositiveInteger", () => {
  it("accepts integers of at least 1", () => {
    expect(isPositiveInteger(1)).toBe(true);
    expect(isPositiveInteger("12")).toBe(true);
    expect(isPositiveInteger(0)).toBe(false);
    expect(isPositiveInteger(1.5)).toBe(false);
    expect(isPositiveInteger("")).toBe(false);
    expect(isPositiveInteger("-3")).toBe(false);
  });
});

describe("isAllowedInterval", () => {
  it("accepts a converted interval through 2922 days", () => {
    expect(MAX_CADENCE_SECONDS).toBe(252460800);
    expect(isAllowedInterval(2922, "days")).toBe(true);
    expect(isAllowedInterval(252460800, "seconds")).toBe(true);
    expect(isAllowedInterval("1", "hours")).toBe(true);
  });

  it("rejects a non-positive amount and a conversion past the horizon", () => {
    expect(isAllowedInterval(0, "days")).toBe(false);
    expect(isAllowedInterval(2923, "days")).toBe(false);
    expect(isAllowedInterval(252460801, "seconds")).toBe(false);
  });
});
