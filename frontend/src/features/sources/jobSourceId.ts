import type { Job } from "@/features/sources/types";

export function jobSourceId(job: Job): string | null {
  const value = job.input?.source_id;
  return typeof value === "string" && value ? value : null;
}
