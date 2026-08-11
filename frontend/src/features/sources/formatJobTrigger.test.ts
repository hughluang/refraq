import { describe, expect, it } from "vitest";

import {
  formatJobTrigger,
  shortTriggerRef,
} from "@/features/sources/formatJobTrigger";

const t = (key: string) =>
  (
    {
      "jobs.trigger.user": "用户",
      "jobs.trigger.schedule": "定时",
      "jobs.trigger.mcp": "MCP",
      "jobs.trigger.system": "系统",
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
          trigger_actor_name: "张三",
        },
        t,
      ),
    ).toBe("用户 · 张三");
  });

  it("falls back to short ref when actor name is missing", () => {
    expect(
      formatJobTrigger(
        {
          trigger_kind: "user",
          trigger_ref: "user_1c9f4f9481de",
          trigger_actor_name: null,
        },
        t,
      ),
    ).toBe("用户 · user_1c9f4f94");
  });

  it("localizes non-user kinds", () => {
    expect(
      formatJobTrigger(
        {
          trigger_kind: "schedule",
          trigger_ref: "sched_1",
          trigger_actor_name: null,
        },
        t,
      ),
    ).toBe("定时 · sched_1");
  });
});
