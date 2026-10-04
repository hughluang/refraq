import { describe, expect, it } from "vitest";

import {
  browserTimeZone,
  displayZoneId,
  formatDurationMs,
  formatInstant,
  formatJobDuration,
  runDurationMs,
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

  it("tries aliases before labeling UTC", () => {
    const value = "2026-08-11T14:20:38.000Z";
    const viaAlias = formatInstant(value, {
      timeZone: "Not/AZone",
      aliases: ["UTC"],
      locale: "en-US",
    });
    expect(viaAlias).toBe(
      new Date(value).toLocaleString("en-US", { timeZone: "UTC" }),
    );
    expect(viaAlias.endsWith(" UTC")).toBe(false);
  });

  it("throws when a valid instant cannot be formatted for the locale", () => {
    const value = "2026-08-11T14:20:38.000Z";
    expect(() => formatInstant(value, { locale: "%%%" })).toThrow(RangeError);
    expect(() =>
      formatInstant(value, {
        timeZone: "Not/AZone",
        aliases: ["Also/Missing"],
        locale: "%%%",
      }),
    ).toThrow(RangeError);
  });

  it("labels UTC when the zone and its aliases are unknown", () => {
    const value = "2026-08-11T14:20:38.000Z";
    const browser = formatInstant(value, { locale: "en-US" });
    const invalid = formatInstant(value, {
      timeZone: "Not/AZone",
      aliases: ["Also/Missing"],
      locale: "en-US",
    });
    const utc = new Date(value).toLocaleString("en-US", { timeZone: "UTC" });
    expect(invalid).toBe(`${utc} UTC`);
    expect(invalid).not.toBe(browser);
  });
});

describe("displayZoneId", () => {
  it("keeps a stored preference and otherwise uses the browser zone", () => {
    expect(displayZoneId("Asia/Shanghai")).toBe("Asia/Shanghai");
    expect(displayZoneId("  UTC  ")).toBe("UTC");
    expect(displayZoneId(null)).toBe(browserTimeZone());
    expect(displayZoneId(undefined)).toBe(browserTimeZone());
    expect(displayZoneId("")).toBe(browserTimeZone());
    expect(displayZoneId("   ")).toBe(browserTimeZone());
  });

  it("does not label a missing browser zone as UTC", () => {
    const original = Intl.DateTimeFormat;
    Intl.DateTimeFormat = function DateTimeFormat() {
      throw new Error("intl down");
    } as unknown as typeof Intl.DateTimeFormat;
    try {
      expect(browserTimeZone()).toBeNull();
      expect(displayZoneId(null)).toBeNull();
      expect(displayZoneId(null)).not.toBe(displayZoneId("UTC"));
    } finally {
      Intl.DateTimeFormat = original;
    }
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

describe("runDurationMs", () => {
  const started = "2026-10-04T10:00:00Z";
  const now = Date.parse("2026-10-04T10:01:00Z");

  it("uses finished minus started", () => {
    expect(
      runDurationMs(
        { status: "succeeded", started_at: started, finished_at: "2026-10-04T10:00:10Z" },
        now,
      ),
    ).toBe(10_000);
  });

  it("uses now for running jobs", () => {
    expect(
      runDurationMs({ status: "running", started_at: started, finished_at: null }, now),
    ).toBe(60_000);
  });

  it("is null when not started", () => {
    expect(
      runDurationMs({ status: "queued", started_at: null, finished_at: null }, now),
    ).toBeNull();
  });

  it("is null when finish precedes start", () => {
    expect(
      runDurationMs(
        { status: "failed", started_at: started, finished_at: "2026-10-04T09:59:00Z" },
        now,
      ),
    ).toBeNull();
  });
});
