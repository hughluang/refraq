import { apiClient } from "@/lib/api";
import type { Job, JobLogs } from "@/features/jobs/types";
import type { OffsetPage } from "@/lib/pagination";

export function listJobs(params?: {
  kind?: string;
  status?: string;
  limit?: number;
  offset?: number;
}) {
  const q = new URLSearchParams();
  if (params?.kind) q.set("kind", params.kind);
  if (params?.status) q.set("status", params.status);
  if (params?.limit != null) q.set("limit", String(params.limit));
  if (params?.offset != null) q.set("offset", String(params.offset));
  const suffix = q.toString() ? `?${q.toString()}` : "";
  return apiClient<OffsetPage<Job>>(`/jobs${suffix}`);
}

export function getJob(jobId: string, init?: { signal?: AbortSignal }) {
  return apiClient<{ job: Job }>(`/jobs/${jobId}`, init);
}

export function getJobLogs(jobId: string, init?: { signal?: AbortSignal }) {
  return apiClient<JobLogs>(`/jobs/${jobId}/logs`, init);
}

export function cancelJob(jobId: string) {
  return apiClient<{ job: Job }>(`/jobs/${jobId}/cancel`, { method: "POST" });
}
