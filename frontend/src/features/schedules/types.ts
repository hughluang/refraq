export type ScheduleTarget = {
  source_id: string | null;
  source_key: string | null;
};

export type ScheduleLastJob = {
  id: string;
  status: string;
  finished_at: string | null;
  created_at: string | null;
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
  schedule_timezone: string;
  last_run_at: string | null;
  next_run_at: string | null;
  last_job: ScheduleLastJob | null;
  created_at: string;
  updated_at: string;
};

export type CreateScheduleBody = {
  kind: "structure";
  cron?: string | null;
  interval_seconds?: number | null;
  schedule_timezone: string;
  enabled: boolean;
  name?: string | null;
};

export type PatchScheduleBody = {
  enabled?: boolean;
  name?: string | null;
  cron?: string | null;
  interval_seconds?: number | null;
  schedule_timezone?: string;
};
