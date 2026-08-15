import { apiClient } from "@/lib/api";
import type { Job, JobLogs } from "@/features/jobs/types";

export function listJobs(params?: { kind?: string; status?: string }) {
  const q = new URLSearchParams();
  if (params?.kind) q.set("kind", params.kind);
  if (params?.status) q.set("status", params.status);
  const suffix = q.toString() ? `?${q.toString()}` : "";
  return apiClient<{ items: Job[] }>(`/jobs${suffix}`);
}

export function getJob(jobId: string) {
  return apiClient<{ job: Job }>(`/jobs/${jobId}`);
}

export function getJobLogs(jobId: string) {
  return apiClient<JobLogs>(`/jobs/${jobId}/logs`);
}

export function cancelJob(jobId: string) {
  return apiClient<{ job: Job }>(`/jobs/${jobId}/cancel`, { method: "POST" });
}
