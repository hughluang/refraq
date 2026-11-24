export type Health = "healthy" | "failed" | "stale" | "unobserved";
export type Link = "replication" | "production" | "consumption" | "storage";
export const LINKS: Link[] = ["replication", "production", "consumption", "storage"];
export type Check = {
  link: Link; health: Health; observed_at: string | null; valid_until: string | null;
  last_success_at: string | null; failure_at: string | null; error_code: string | null;
};
export type Round = { id: string; at: string; health: Health; checks: Check[] };
export type SourceDiagnostic = {
  id: string; name: string; runtime_instance_id: string | null; health: Health; checks: Check[];
  history: (Round | null)[]; last_checked_at: string | null; end_of_cycle_wait_seconds: number | null;
};
export type Window = { observed_at: string; valid_until: string };
export type MirrorSample = Window & {
  generation_id: string; mirror_id: string; interval_start: string; interval_end: string; stale: boolean;
  captured_events: number | null; committed_events: number | null; committed_batches: number | null;
  pending_events: number | null; pending_bytes: number | null; position_lag: number | null;
  capture_state: string; write_state: string; last_target_commit_at: string | null; freshness_ms: number | null;
};
export type Measurements = {
  mirror_id: string; source_id: string; sample: MirrorSample | null;
  row_sample: (Window & { generation_id: string; row_count: number }) | null; row_sample_stale: boolean;
  estimated_rows: number | null; published_generation_id: string | null;
  runtime_instance_id: string | null; last_source_check_at: string | null; end_of_cycle_wait_seconds: number | null;
};
export type Metric = {
  value: number | null; sampled: number; missing: number; interval_start: string | null; interval_end: string | null;
  oldest_observation: string | null; newest_observation: string | null;
};
export type RuntimeDiagnostic = {
  id: string; heartbeat: Window | null; heartbeat_health: Health; cycle_health: Health; assignment_stale: boolean;
  cycle: (Window & { started_at: string; completed_at: string | null; duration_seconds: number | null;
    last_completed_at: string | null; last_duration_seconds: number | null }) | null;
  end_of_cycle_wait_seconds: number | null; source_ids: string[]; assignment_offset: number; total_sources: number;
};
export type Diagnostics = {
  observed_at: string; mirror_count: number; source_count: number; sources: SourceDiagnostic[];
  matching_sources: number; source_offset: number; runtimes: RuntimeDiagnostic[]; runtime_offset: number;
  assignment_offset: number; total_runtimes: number; link_counts: Record<Health, number>;
  summary: Record<"captured_events" | "committed_events" | "committed_batches" | "pending_events" | "pending_bytes" | "position_lag", Metric>;
  states: Record<"capture" | "write", Record<"active" | "idle" | "blocked" | "unobserved", number>>;
  intervals: { mirror_id: string; qualified_table: string; interval_start: string | null; interval_end: string | null;
    observed_at: string | null; stale: boolean }[];
};
