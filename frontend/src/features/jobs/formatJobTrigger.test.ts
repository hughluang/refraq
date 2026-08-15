import { describe, expect, it } from "vitest";

import {
  formatJobTrigger,
  shortTriggerRef,
} from "@/features/jobs/formatJobTrigger";

const t = (key: string) =>
  (
    {
      "jobs.trigger.user": "User",
      "jobs.trigger.schedule": "Schedule",
      "jobs.trigger.mcp": "MCP",
      "jobs.trigger.system": "System",
    } as Record<string, string>
  )[key] ?? key;

describe("shortTriggerRef", () => {
  it("keeps short user ids", () => {
    expect(shortTriggerRef("user_abc")).toBe("user_abc");
  });

  it("truncates long user suffix to 8 chars", () => {
    expect(shortTriggerRef("user_1c9f4f9481de")).toBe("user_1c9f4f94");
  });

  it("leaves non-user refs unchanged", () => {
    expect(shortTriggerRef("sched_1")).toBe("sched_1");
  });
});

describe("formatJobTrigger", () => {
  it("returns em dash when kind is missing", () => {
    expect(
      formatJobTrigger(
        {
          trigger_kind: null,
          trigger_ref: null,
          trigger_actor_name: null,
          trigger_schedule_name: null,
        },
        t,
      ),
    ).toBe("—");
  });

  it("prefers actor display name for user triggers", () => {
    expect(
      formatJobTrigger(
        {
          trigger_kind: "user",
          trigger_ref: "user_1c9f4f9481de",
          trigger_actor_name: "Alice",
          trigger_schedule_name: null,
        },
        t,
      ),
    ).toBe("User · Alice");
  });

  it("falls back to short ref when actor name is missing", () => {
    expect(
      formatJobTrigger(
        {
          trigger_kind: "user",
          trigger_ref: "user_1c9f4f9481de",
          trigger_actor_name: null,
          trigger_schedule_name: null,
        },
        t,
      ),
    ).toBe("User · user_1c9f4f94");
  });

  it("prefers schedule name for schedule triggers", () => {
    expect(
      formatJobTrigger(
        {
          trigger_kind: "schedule",
          trigger_ref: "sched_1",
          trigger_actor_name: null,
          trigger_schedule_name: "structure · mes-prod",
        },
        t,
      ),
    ).toBe("Schedule · structure · mes-prod");
  });

  it("falls back to trigger_ref when schedule name is missing", () => {
    expect(
      formatJobTrigger(
        {
          trigger_kind: "schedule",
          trigger_ref: "sched_1",
          trigger_actor_name: null,
          trigger_schedule_name: null,
        },
        t,
      ),
    ).toBe("Schedule · sched_1");
  });
});
