import { afterEach, describe, expect, it, vi } from "vitest";

import { createSourceSchedule } from "@/features/schedules/api";
import type { ScheduledTask } from "@/features/schedules/types";
import { wallToInstant } from "@/lib/wall-time";

const SUBMITTED = "2026-10-11T06:00:29Z";

function schedule(startAt: string): ScheduledTask {
  return {
    id: "sch_1",
    key: "nightly",
    name: "Nightly",
    enabled: true,
    work_kind: "structure",
    target: { source_id: "src_1" },
    interval_seconds: null,
    cron: "0 0 * * *",
    running_timeout_sec: null,
    start_at: startAt,
    deletable: true,
    last_run_at: null,
    next_run_at: null,
    recent_jobs: [],
    created_at: SUBMITTED,
    updated_at: SUBMITTED,
  };
}

describe("schedule start readback", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("reads back the same second-precision string that was submitted", async () => {
    const startAt = wallToInstant("2026-10-11 14:00:29", "Asia/Shanghai");
    expect(startAt).toBe(SUBMITTED);

    vi.stubGlobal(
      "fetch",
      vi.fn(async (_url: string, init?: RequestInit) => {
        const sent = JSON.parse(String(init?.body)) as { start_at: string };
        return new Response(JSON.stringify({ schedule: schedule(sent.start_at) }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );

    const saved = await createSourceSchedule("src_1", {
      kind: "structure",
      cron: "0 0 * * *",
      start_at: startAt,
      enabled: true,
    });

    expect(saved.schedule.start_at).toBe(SUBMITTED);
  });
});
