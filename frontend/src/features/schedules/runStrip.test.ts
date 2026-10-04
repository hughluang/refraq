import { describe, expect, it } from "vitest";

import {
  RUN_BAR_MIN_RATIO,
  barHeightRatio,
  buildRunSlots,
} from "@/features/schedules/runStrip";
import type { ScheduleRecentJob } from "@/features/schedules/types";

function job(id: string, over: Partial<ScheduleRecentJob> = {}): ScheduleRecentJob {
  return {
    id,
    status: "succeeded",
    created_at: "2026-10-04T10:00:00Z",
    started_at: "2026-10-04T10:00:00Z",
    finished_at: "2026-10-04T10:00:10Z",
    error_code: null,
    ...over,
  };
}

describe("buildRunSlots", () => {
  it("pads empty slots on the left", () => {
    const slots = buildRunSlots([job("a"), job("b")], 5);
    expect(slots.map((s) => s?.id ?? null)).toEqual([null, null, null, "a", "b"]);
  });

  it("keeps the newest when over capacity", () => {
    const slots = buildRunSlots([job("a"), job("b"), job("c")], 2);
    expect(slots.map((s) => s?.id)).toEqual(["b", "c"]);
  });

  it("fills all slots with placeholders when empty", () => {
    expect(buildRunSlots([], 3)).toEqual([null, null, null]);
  });
});

describe("barHeightRatio", () => {
  it("uses the minimum for unknown duration", () => {
    expect(barHeightRatio(null, 1000)).toBe(RUN_BAR_MIN_RATIO);
    expect(barHeightRatio(500, 0)).toBe(RUN_BAR_MIN_RATIO);
  });

  it("reaches full height for the longest run", () => {
    expect(barHeightRatio(1000, 1000)).toBeCloseTo(1);
  });

  it("is monotonic", () => {
    expect(barHeightRatio(100, 10_000)).toBeLessThan(barHeightRatio(1000, 10_000));
  });
});
