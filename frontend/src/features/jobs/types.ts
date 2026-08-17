export type Job = {
  id: string;
  kind: string;
  status: string;
  input: Record<string, unknown>;
  result: Record<string, unknown> | null;
  summary: string;
  trigger_kind: string | null;
  trigger_ref: string | null;
  trigger_actor_name: string | null;
  trigger_schedule_name: string | null;
  created_by_user_id: string | null;
  running_timeout_sec?: number | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error_code: string | null;
  error_message: string | null;
  log_updated_at?: string | null;
};

export type JobLogs = {
  job_id: string;
  body: string;
  updated_at: string | null;
};
