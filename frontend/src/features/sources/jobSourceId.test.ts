import { describe, expect, it } from "vitest";

import { jobSourceId } from "@/features/sources/jobSourceId";
import type { Job } from "@/features/sources/types";

function job(input: Record<string, unknown>): Job {
  return {
    id: "job_1",
    kind: "structure",
    status: "succeeded",
    input,
    result: null,
    summary: "",
    trigger_kind: null,
    trigger_ref: null,
    trigger_actor_name: null,
    created_by_user_id: null,
    created_at: "2026-01-01T00:00:00Z",
    started_at: null,
    finished_at: null,
    error_code: null,
    error_message: null,
  };
}

describe("jobSourceId", () => {
  it("reads source_id from job input", () => {
    expect(jobSourceId(job({ source_id: "src_1" }))).toBe("src_1");
  });

  it("returns null when source_id is missing or not a string", () => {
    expect(jobSourceId(job({}))).toBeNull();
    expect(jobSourceId(job({ source_id: 1 }))).toBeNull();
  });
});
