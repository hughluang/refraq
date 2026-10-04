import { describe, expect, it } from "vitest";

import {
  formatScheduleNextRun,
  nextRunPreview,
} from "@/features/schedules/nextRunPreview";

const daily = { cadence: "daily" as const, cron: "0 2 * * *", interval_seconds: 3600 };
const savedDaily = { cron: "0 2 * * *", interval_seconds: null };

describe("nextRunPreview", () => {
  it("hides the note when creating", () => {
    expect(nextRunPreview(null, daily)).toBe("hidden");
    expect(nextRunPreview(undefined, daily)).toBe("hidden");
  });

  it("shows the saved instant while the expression is unchanged", () => {
    expect(nextRunPreview(savedDaily, daily)).toBe("saved");
    expect(
      nextRunPreview(savedDaily, { ...daily, cron: "  0 2 * * *  " }),
    ).toBe("saved");
    expect(
      nextRunPreview(savedDaily, {
        cadence: "custom",
        cron: "0 2 * * *",
        interval_seconds: 3600,
      }),
    ).toBe("saved");
  });

  it("refuses a new clock when the cadence changed", () => {
    expect(
      nextRunPreview(savedDaily, { ...daily, cron: "0 3 * * *" }),
    ).toBe("recalculates");
    expect(
      nextRunPreview(savedDaily, {
        cadence: "weekly",
        cron: "0 2 * * 1",
        interval_seconds: 3600,
      }),
    ).toBe("recalculates");
    expect(
      nextRunPreview(savedDaily, {
        cadence: "interval",
        cron: "0 2 * * *",
        interval_seconds: 3600,
      }),
    ).toBe("recalculates");
  });

  it("matches an interval only when the seconds are the same number", () => {
    const saved = { cron: null, interval_seconds: 3600 };
    expect(
      nextRunPreview(saved, {
        cadence: "interval",
        cron: "",
        interval_seconds: "3600",
      }),
    ).toBe("saved");
    expect(
      nextRunPreview(saved, {
        cadence: "interval",
        cron: "",
        interval_seconds: 1800,
      }),
    ).toBe("recalculates");
    expect(
      nextRunPreview(saved, {
        cadence: "interval",
        cron: "",
        interval_seconds: "",
      }),
    ).toBe("recalculates");
    expect(nextRunPreview(saved, daily)).toBe("recalculates");
  });
});

describe("formatScheduleNextRun", () => {
  const formatInstant = (value: string | null | undefined) =>
    value ? `fmt:${value}` : "—";

  it("uses the list's paused label, instant, or em dash", () => {
    expect(
      formatScheduleNextRun(
        { enabled: false, next_run_at: "2026-10-04T02:00:00Z" },
        formatInstant,
        "Paused",
      ),
    ).toBe("Paused");
    expect(
      formatScheduleNextRun(
        { enabled: true, next_run_at: "2026-10-04T02:00:00Z" },
        formatInstant,
        "Paused",
      ),
    ).toBe("fmt:2026-10-04T02:00:00Z");
    expect(
      formatScheduleNextRun(
        { enabled: true, next_run_at: null },
        formatInstant,
        "Paused",
      ),
    ).toBe("—");
  });
});
