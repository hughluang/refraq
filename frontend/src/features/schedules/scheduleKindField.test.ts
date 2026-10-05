import { describe, expect, it } from "vitest";

import { scheduleKindFromTask } from "@/features/schedules/scheduleKindField";

describe("scheduleKindFromTask", () => {
  it("maps work_kind onto the create-form kind", () => {
    expect(scheduleKindFromTask("join_detection")).toBe("join_detection");
    expect(scheduleKindFromTask("structure")).toBe("structure");
    expect(scheduleKindFromTask(null)).toBe("structure");
    expect(scheduleKindFromTask(undefined)).toBe("structure");
  });
});
