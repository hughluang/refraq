import { apiClient } from "@/lib/api";
import type {
  PatchScheduleBody,
  PutScheduleBody,
  ScheduledTask,
} from "@/features/schedules/types";

export function listSchedules() {
  return apiClient<{ items: ScheduledTask[] }>("/schedules");
}

export function getSourceSchedule(sourceId: string) {
  return apiClient<{ schedule: ScheduledTask }>(
    `/sources/${sourceId}/schedule`,
  );
}

export function putSourceSchedule(sourceId: string, body: PutScheduleBody) {
  return apiClient<{ schedule: ScheduledTask }>(
    `/sources/${sourceId}/schedule`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

export function deleteSourceSchedule(sourceId: string) {
  return apiClient<void>(`/sources/${sourceId}/schedule`, { method: "DELETE" });
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
