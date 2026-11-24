import type { Check, Diagnostics, Measurements, SourceDiagnostic } from "./diagnosticTypes";
import { LINKS } from "./diagnosticTypes";

export const observed = "2026-11-23T12:00:00Z";
const valid = "2026-11-23T12:02:00Z";
const interval = { interval_start: "2026-11-23T11:59:50Z", interval_end: observed };
export function diagnosticFixture(): Diagnostics {
  const sources: SourceDiagnostic[] = Array.from({ length: 3 }, (_, i) => ({
    id: `source-${i + 1}`, name: ["Commerce", "Warehouse", "Billing"][i], runtime_instance_id: "runtime-eu-1",
    health: i === 1 ? "failed" : i === 2 ? "stale" : "healthy",
    checks: LINKS.map((link, j): Check => ({ link, health: i === 1 && j === 1 ? "failed" : i === 2 ? "stale" : "healthy",
      observed_at: observed, valid_until: valid, last_success_at: observed,
      failure_at: i === 1 && j === 1 ? observed : null,
      error_code: i === 1 && j === 1 ? "PRODUCTION_UNAVAILABLE" : null })),
    history: Array.from({ length: 16 }, (_, j) => j < 4 ? null : { id: `${i}-${j}`, at: observed,
      health: j === 11 && i === 1 ? "failed" : "healthy", checks: LINKS.map(link => ({ link, health: "healthy", observed_at: observed,
        valid_until: valid, last_success_at: observed, failure_at: null, error_code: null })) }),
    last_checked_at: observed, end_of_cycle_wait_seconds: 10,
  }));
  const metric = { value: 2400, sampled: 2, missing: 1, ...interval, oldest_observation: "2026-11-23T11:59:58Z", newest_observation: observed };
  return { observed_at: observed, mirror_count: 3, source_count: 3, sources, matching_sources: 3, source_offset: 0,
    runtimes: [{ id: "runtime-eu-1", heartbeat: { observed_at: observed, valid_until: valid }, heartbeat_health: "stale", cycle_health: "healthy",
      cycle: { observed_at: observed, valid_until: valid, started_at: interval.interval_start, completed_at: observed,
        duration_seconds: 10, last_completed_at: observed, last_duration_seconds: 10 }, assignment_stale: false,
      end_of_cycle_wait_seconds: 10, source_ids: Array.from({ length: 8 }, (_, i) => `source-${i + 1}`), assignment_offset: 0, total_sources: 12 }],
    runtime_offset: 0, assignment_offset: 0, total_runtimes: 4,
    link_counts: { healthy: 7, failed: 1, stale: 4, unobserved: 0 },
    summary: { captured_events: { ...metric }, committed_events: { ...metric, value: 1800 },
      committed_batches: { ...metric, value: 9 }, position_lag: { ...metric, value: 850 },
      pending_events: { ...metric, value: null, sampled: 0, missing: 3 }, pending_bytes: { ...metric, value: null, sampled: 0, missing: 3 } },
    states: { capture: { active: 1, idle: 1, blocked: 1, unobserved: 0 }, write: { active: 1, idle: 1, blocked: 0, unobserved: 1 } },
    intervals: [{ mirror_id: "mirror-1", qualified_table: "public.orders", ...interval, observed_at: observed, stale: false },
      { mirror_id: "mirror-2", qualified_table: "public.inventory", interval_start: "2026-11-23T11:59:48Z", interval_end: "2026-11-23T11:59:58Z", observed_at: "2026-11-23T11:59:58Z", stale: false },
      { mirror_id: "mirror-3", qualified_table: "public.invoices", interval_start: null, interval_end: null, observed_at: null, stale: false }],
  };
}

export function measurementsFixture(): Measurements {
  return { mirror_id: "mirror-1", source_id: "source-1", runtime_instance_id: "runtime-eu-1", last_source_check_at: observed,
    end_of_cycle_wait_seconds: 10, estimated_rows: 100000, published_generation_id: "generation-current", row_sample_stale: false,
    row_sample: { observed_at: observed, valid_until: valid, generation_id: "generation-current", row_count: 100240 },
    sample: { mirror_id: "mirror-1", generation_id: "generation-current", ...interval, observed_at: observed, valid_until: valid, stale: false,
      captured_events: 2400, committed_events: 1800, committed_batches: 9, pending_events: null, pending_bytes: null, position_lag: 850,
      capture_state: "active", write_state: "active", last_target_commit_at: observed, freshness_ms: null } };
}
