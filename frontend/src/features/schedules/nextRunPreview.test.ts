import { describe, expect, it } from "vitest";

import { formatScheduleNextRun } from "@/features/schedules/nextRunPreview";

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
