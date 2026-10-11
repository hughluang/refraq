import { describe, expect, it } from "vitest";

import { formatScheduleNextRun } from "@/features/schedules/nextRunPreview";
import { Instant } from "@/lib/instant";

describe("formatScheduleNextRun", () => {
  const formatInstant = (value: Instant | null | undefined) =>
    value ? `fmt:${value.toJSON()}` : "—";
  const at = Instant.parse("2026-10-04T02:00:00Z");

  it("uses the list's paused label, instant, or em dash", () => {
    expect(
      formatScheduleNextRun(
        { enabled: false, next_run_at: at },
        formatInstant,
        "Paused",
      ),
    ).toBe("Paused");
    expect(
      formatScheduleNextRun(
        { enabled: true, next_run_at: at },
        formatInstant,
        "Paused",
      ),
    ).toBe(`fmt:${at.toJSON()}`);
    expect(
      formatScheduleNextRun(
        { enabled: true, next_run_at: null },
        formatInstant,
        "Paused",
      ),
    ).toBe("—");
  });
});
