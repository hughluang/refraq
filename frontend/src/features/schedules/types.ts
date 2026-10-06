export type ScheduleTarget = {
  source_id: string | null;
  source_key: string | null;
};

export type ScheduleRecentJob = {
  id: string;
  status: string;
  created_at: string | null;
  started_at: string | null;
  finished_at: string | null;
  error_code: string | null;
};

export type ScheduledTask = {
  id: string;
  key: string;
  name: string;
  enabled: boolean;
  work_kind: string | null;
  target: ScheduleTarget | null;
  interval_seconds: number | null;
  cron: string | null;
  running_timeout_sec: number | null;
  /** Schedule Start Instant; null means start immediately. */
  start_at: string | null;
  deletable: boolean;
  last_run_at: string | null;
  next_run_at: string | null;
  /** Latest Jobs of this schedule, oldest first; the last element is the last run. */
  recent_jobs: ScheduleRecentJob[];
  created_at: string;
  updated_at: string;
};

export type CreateScheduleBody = {
  kind: "structure" | "join_detection";
  cron?: string | null;
  interval_seconds?: number | null;
  running_timeout_sec?: number | null;
  start_at?: string | null;
  enabled: boolean;
  name?: string | null;
};

export type PatchScheduleBody = {
  enabled?: boolean;
  name?: string | null;
  cron?: string | null;
  interval_seconds?: number | null;
  running_timeout_sec?: number | null;
  start_at?: string | null;
};
