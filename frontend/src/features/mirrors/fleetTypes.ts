import type { OffsetPage } from "@/lib/pagination";
import type { Health, Link } from "./diagnosticTypes";
import type { Mirror } from "./types";

export type OperationsScope = { source_id?: string; runtime_id?: string };
export const FLEET_STATES = ["synchronizing", "copying", "attention", "stopped"] as const;
export type FleetState = typeof FLEET_STATES[number];
export const ATTENTION_CAUSES = ["schema", "permission", "continuity", "pending_stop", "source_prerequisite", "snapshot_evidence"] as const;
export type AttentionCause = typeof ATTENTION_CAUSES[number];
export type FleetMeasure = { value: number | null; sampled: number; missing: number };
export type SourceFleet = {
  id: string; name: string; runtime_instance_id: string | null; health: Health;
  segment_health: Record<Link, Health>; mirror_count: number; attention_count: number;
  source_size: FleetMeasure; estimated_rows: FleetMeasure;
};
export type RuntimeFleet = {
  id: string; runtime_instance_id: string | null; source_count: number;
  affected_source_count: number; health: Health;
};
export type FleetOverview = {
  observed_at: string; mirror_count: number; source_count: number;
  source_size: FleetMeasure; estimated_rows: FleetMeasure;
  published_count: number; published_percent: number | null; attention_count: number;
  states: Record<FleetState, { count: number; percent: number | null }>;
  snapshot: { scanned_bytes: number | null; source_size_bytes: number | null; sampled: number; missing: number; queued: number };
  health: Record<Health, number>; segments: Record<Link, Record<Health, number>>;
  ranking: SourceFleet[]; ranking_total: number;
};
export type InventoryMirror = Mirror & {
  grouped_state: FleetState; attention_cause: AttentionCause | null; attention_since: string | null;
  source_size_bytes: number | null; estimated_rows: number | null;
};
export type InventoryPage = OffsetPage<InventoryMirror> & { cause_counts: Partial<Record<AttentionCause, number>> };
export type FleetSearch = OperationsScope & { q?: string; health?: string; segment?: string; limit: number; offset: number };
export type InventoryQuery = OperationsScope & {
  q?: string; grouped_state?: string; published_only?: boolean; cause?: string;
  sort?: string; limit: number; offset: number;
};
export type ThroughputRate = {
  value: number | null; sampled: number; missing: number;
  interval_start: string | null; interval_end: string | null;
  oldest_observation: string | null; newest_observation: string | null; measured_seconds: number;
};
export type ThroughputPoint = { at: string; bucket_start: string; received: ThroughputRate; committed: ThroughputRate };
export type FleetThroughput = {
  observed_at: string; window_start: string; window_end: string; hours: number; unit: "MB/s";
  mirror_count: number; source_count: number; points: ThroughputPoint[];
};
