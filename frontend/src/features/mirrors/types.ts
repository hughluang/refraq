export const MIRROR_STATUSES = ["waiting", "snapshotting", "catching_up", "ready", "stale", "rebuilding", "paused", "needs_attention", "disable_pending", "unknown", "disabled", "source_fault"] as const;
export type RecoveryAction = "retry" | "run_now" | "postpone" | "manual";
export type RecoveryRequest = {
  action: RecoveryAction;
  expected_history_epoch: string | number;
  reason?: string;
};
export type ReadinessItem = {
  key: string;
  result: "pass" | "fail" | "unknown" | "not_applicable";
  expected: unknown;
  observed: unknown;
  observed_at: string | null;
  owner: string;
  action: string;
};
type StopAcknowledgment = {
  operation_id: string;
  source_operation_id: string;
  observed_at: string;
};
type MirrorControl = {
  control_revision: number;
  credential_revision: number | null;
  owner_epoch: number | null;
  runtime_instance_id: string | null;
  applied_revision: number | null;
  observed_at: string | null;
  stop_ack: StopAcknowledgment | null;
};
type MirrorOperation = {
  id: string;
  mirror_id: string;
  kind: "open" | "enable" | "disable" | "recovery";
  state: "pending" | "applied" | "superseded";
  control_revision: number;
  observed_evidence_refs: string[];
  fault_code: string | null;
  requested_at: string;
};
export type Mirror = {
  id: string;
  source_id: string;
  source_key: string;
  source_name: string;
  object_id: string;
  table_identity: string;
  qualified_table: string;
  enabled: boolean;
  status: (typeof MIRROR_STATUSES)[number];
  published_generation_id: string | null;
  capture_generation: string | null;
  history_epoch: string | number | null;
  retained_lower_bound: unknown;
  committed_upper_bound: unknown;
  control: MirrorControl;
  progress: { stage: "scan" | "catching_up"; notification_offset: number; observed_at: string | null; generation_id: string } | null;
  profile: Record<string, unknown>;
  readiness: ReadinessItem[];
  fault: Record<string, unknown> | null;
  operations: MirrorOperation[];
};
export type PendingOperation = { operation_id: string; state: "pending" };
