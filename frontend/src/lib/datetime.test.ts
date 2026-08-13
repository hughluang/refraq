import { describe, expect, it } from "vitest";

import {
  formatDurationMs,
  formatInstant,
  formatJobDuration,
} from "@/lib/datetime";

describe("formatInstant", () => {
  it("returns em dash for empty values", () => {
    expect(formatInstant(null)).toBe("—");
    expect(formatInstant(undefined)).toBe("—");
    expect(formatInstant("")).toBe("—");
  });

  it("returns em dash for invalid dates", () => {
    expect(formatInstant("not-a-date")).toBe("—");
  });

  it("formats a valid ISO instant via browser default", () => {
    const value = "2026-08-11T14:20:38.676492Z";
    expect(formatInstant(value)).toBe(new Date(value).toLocaleString());
  });

  it("formats with an explicit IANA timeZone", () => {
    const value = "2026-08-11T14:20:38.000Z";
    const formatted = formatInstant(value, {
      timeZone: "UTC",
      locale: "en-US",
    });
    expect(formatted).toBe(
      new Date(value).toLocaleString("en-US", { timeZone: "UTC" }),
    );
  });

  it("formats Asia/Shanghai differently from UTC for the same Instant", () => {
    const value = "2026-08-11T14:20:38.000Z";
    const utc = formatInstant(value, { timeZone: "UTC", locale: "en-US" });
    const shanghai = formatInstant(value, {
      timeZone: "Asia/Shanghai",
      locale: "en-US",
    });
    expect(shanghai).not.toBe(utc);
  });

  it("returns em dash for invalid timeZone (not browser fallback)", () => {
    const value = "2026-08-11T14:20:38.000Z";
    const browser = formatInstant(value, { locale: "en-US" });
    const invalid = formatInstant(value, {
      timeZone: "Not/AZone",
      locale: "en-US",
    });
    expect(invalid).toBe("—");
    expect(invalid).not.toBe(browser);
  });
});

describe("formatDurationMs", () => {
  it("formats sub-second as ms", () => {
    expect(formatDurationMs(320)).toBe("320ms");
    expect(formatDurationMs(0)).toBe("0ms");
  });

  it("formats seconds", () => {
    expect(formatDurationMs(1000)).toBe("1s");
    expect(formatDurationMs(45_000)).toBe("45s");
  });

  it("formats minutes and seconds", () => {
    expect(formatDurationMs(125_000)).toBe("2m 5s");
    expect(formatDurationMs(120_000)).toBe("2m");
  });

  it("formats hours", () => {
    expect(formatDurationMs(3_661_000)).toBe("1h 1m 1s");
    expect(formatDurationMs(3_600_000)).toBe("1h 0m");
  });

  it("returns em dash for invalid input", () => {
    expect(formatDurationMs(-1)).toBe("—");
    expect(formatDurationMs(Number.NaN)).toBe("—");
  });
});

describe("formatJobDuration", () => {
  const started = "2026-08-11T10:00:00.000Z";
  const finished = "2026-08-11T10:00:45.000Z";

  it("uses finished - started when both present", () => {
    expect(
      formatJobDuration({
        status: "succeeded",
        started_at: started,
        finished_at: finished,
      }),
    ).toBe("45s");
  });

  it("uses now - started for running jobs", () => {
    const now = new Date("2026-08-11T10:02:00.000Z");
    expect(
      formatJobDuration(
        { status: "running", started_at: started, finished_at: null },
        now,
      ),
    ).toBe("2m");
  });

  it("returns em dash for queued without start", () => {
    expect(
      formatJobDuration({
        status: "queued",
        started_at: null,
        finished_at: null,
      }),
    ).toBe("—");
  });

  it("returns em dash when started but not running and not finished", () => {
    expect(
      formatJobDuration({
        status: "cancelled",
        started_at: started,
        finished_at: null,
      }),
    ).toBe("—");
  });
});
