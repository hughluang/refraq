import { describe, expect, it } from "vitest";

import {
  dailyPresetLabelKey,
  defaultCron,
  isDailyCron,
  scheduleKindFromTask,
} from "@/features/schedules/scheduleKindField";

describe("defaultCron", () => {
  it("uses 04:00 UTC for join detection and 02:00 UTC for structure", () => {
    expect(defaultCron("join_detection")).toBe("0 4 * * *");
    expect(defaultCron("structure")).toBe("0 2 * * *");
  });
});

describe("scheduleKindFromTask", () => {
  it("maps work_kind onto the create-form kind", () => {
    expect(scheduleKindFromTask("join_detection")).toBe("join_detection");
    expect(scheduleKindFromTask("structure")).toBe("structure");
    expect(scheduleKindFromTask(null)).toBe("structure");
    expect(scheduleKindFromTask(undefined)).toBe("structure");
  });
});

describe("dailyPresetLabelKey", () => {
  it("points at kind-specific daily copy keys", () => {
    expect(dailyPresetLabelKey("structure")).toBe(
      "schedules.preset.dailyStructure",
    );
    expect(dailyPresetLabelKey("join_detection")).toBe(
      "schedules.preset.dailyJoinDetection",
    );
  });
});

describe("isDailyCron", () => {
  it("matches the product-default daily cron for that kind", () => {
    expect(isDailyCron("0 2 * * *", "structure")).toBe(true);
    expect(isDailyCron("0 4 * * *", "join_detection")).toBe(true);
    expect(isDailyCron("0 4 * * *", "structure")).toBe(false);
    expect(isDailyCron("0 2 * * *", "join_detection")).toBe(false);
  });
});
