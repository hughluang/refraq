import { apiClient } from "@/lib/api";
import type { Job } from "@/features/jobs/types";
import type {
  CreateScheduleBody,
  PatchScheduleBody,
  ScheduledTask,
} from "@/features/schedules/types";
import type { OffsetPage } from "@/lib/pagination";

export type ScheduleListPage = OffsetPage<ScheduledTask> & {
  cron_timezone: string;
};

export function listSchedules(params?: { limit?: number; offset?: number }) {
  const qs = new URLSearchParams();
  if (params?.limit != null) qs.set("limit", String(params.limit));
  if (params?.offset != null) qs.set("offset", String(params.offset));
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return apiClient<ScheduleListPage>(`/schedules${suffix}`);
}

export function listSourceSchedules(
  sourceId: string,
  params?: { limit?: number; offset?: number },
) {
  const qs = new URLSearchParams();
  if (params?.limit != null) qs.set("limit", String(params.limit));
  if (params?.offset != null) qs.set("offset", String(params.offset));
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return apiClient<ScheduleListPage>(
    `/sources/${sourceId}/schedules${suffix}`,
  );
}

export function createSourceSchedule(
  sourceId: string,
  body: CreateScheduleBody,
) {
  return apiClient<{ schedule: ScheduledTask }>(
    `/sources/${sourceId}/schedules`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

export type CronPreview = {
  cron_timezone: string;
  next_run_ats: string[];
};

export function previewCron(cron: string, startAt: string | null = null) {
  return apiClient<CronPreview>("/schedules/cron-preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ cron, start_at: startAt }),
  });
}

export function patchSchedule(scheduleId: string, body: PatchScheduleBody) {
  return apiClient<{ schedule: ScheduledTask }>(`/schedules/${scheduleId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function deleteSchedule(scheduleId: string) {
  return apiClient<void>(`/schedules/${scheduleId}`, { method: "DELETE" });
}

export function runSchedule(scheduleId: string) {
  return apiClient<{ job: Job }>(`/schedules/${scheduleId}/run`, {
    method: "POST",
  });
}

export function listScheduleJobs(
  scheduleId: string,
  params?: { kind?: string; status?: string; limit?: number; offset?: number },
) {
  const q = new URLSearchParams();
  if (params?.kind) q.set("kind", params.kind);
  if (params?.status) q.set("status", params.status);
  if (params?.limit != null) q.set("limit", String(params.limit));
  if (params?.offset != null) q.set("offset", String(params.offset));
  const suffix = q.toString() ? `?${q.toString()}` : "";
  return apiClient<OffsetPage<Job>>(`/schedules/${scheduleId}/jobs${suffix}`);
}
