import type { Health, Link } from "./diagnosticTypes";
import { LINKS } from "./diagnosticTypes";
import type { FleetOverview, FleetSearch, FleetState, FleetThroughput, InventoryMirror, InventoryPage, InventoryQuery, OperationsScope, RuntimeFleet, SourceFleet, ThroughputRate } from "./fleetTypes";
import { ATTENTION_CAUSES, FLEET_STATES } from "./fleetTypes";

export const fleetObservedAt = "2026-11-24T12:00:00Z";
const healthOrder: Health[] = ["failed", "stale", "unobserved", "healthy"];
const measure = (value: number | null, count = 1) => ({ value, sampled: value == null ? 0 : count, missing: value == null ? count : 0 });
const emptyHealth = () => ({ failed: 0, stale: 0, unobserved: 0, healthy: 0 });

/** Deterministic synthetic browser data. Every Source has three Mirrors, including retained stopped copies. */
export function createFleetFixture(count = 1024) {
  const sources: SourceFleet[] = [];
  const mirrors: InventoryMirror[] = [];
  for (let index = 0; index < count; index++) {
    const id = `source-${String(index + 1).padStart(4, "0")}`;
    const runtime = `capture-${String(Math.floor(index / 32) + 1).padStart(2, "0")}`;
    const health: Health = index % 11 === 0 ? "failed" : index % 13 === 0 ? "stale" : index % 17 === 0 ? "unobserved" : "healthy";
    const segment_health: Record<Link, Health> = { replication: "healthy", production: "healthy", consumption: "healthy", storage: "healthy" };
    segment_health[LINKS[index % LINKS.length]] = health;
    for (let table = 0; table < 3; table++) {
      const number = index * 3 + table;
      const state: FleetState = FLEET_STATES[number % 4];
      const retained = state === "stopped" && index % 2 === 0;
      const published = state === "synchronizing" || retained || (state === "attention" && index % 2 === 0);
      const cause = state === "attention" ? ATTENTION_CAUSES[Math.floor(number / 4) % ATTENTION_CAUSES.length] : null;
      const status = state === "synchronizing" ? "ready" : state === "stopped" ? "disabled" : state === "attention" ? (cause === "pending_stop" ? "disable_pending" : "needs_attention") : table === 1 ? "snapshotting" : "waiting";
      mirrors.push({
        id: `mirror-${String(number + 1).padStart(5, "0")}`, source_id: id, source_key: id, source_name: `PostgreSQL ${String(index + 1).padStart(4, "0")}`, source_engine: "postgresql",
        object_id: `object-${number}`, table_identity: `table-${number}`, qualified_table: `public.${["orders", "events", "balances"][table]}_${String(index + 1).padStart(4, "0")}`,
        enabled: state !== "stopped" && cause !== "pending_stop", status, grouped_state: state,
        published_generation_id: published ? `generation-${number}` : null, capture_generation: null, history_epoch: published ? 1 : null,
        retained_lower_bound: null, committed_upper_bound: null,
        control: { control_revision: 1, credential_revision: 1, owner_epoch: 1, runtime_instance_id: runtime, applied_revision: 1, observed_at: fleetObservedAt, stop_ack: null },
        progress: status === "snapshotting" ? { stage: "scan", generation_id: `copy-${number}`, notification_offset: 1,
          observed_at: fleetObservedAt, scanned_bytes: (index + 1) * 1_000_000, byte_notification_offset: 1, bytes_observed_at: fleetObservedAt, scan_percent: 50, scan_complete: false } : null,
        profile: {}, readiness: [], fault: null, operations: [],
        attention_cause: cause, attention_since: cause ? new Date(Date.parse(fleetObservedAt) - (count - index) * 60_000).toISOString() : null,
        source_size_bytes: (index + 1) * 2_000_000, estimated_rows: (index + 1) * 20_000,
      });
    }
    const own = mirrors.slice(-3);
    sources.push({ id, name: `PostgreSQL ${String(index + 1).padStart(4, "0")}`, runtime_instance_id: runtime, health, segment_health,
      mirror_count: own.length, attention_count: own.filter(row => row.grouped_state === "attention").length,
      source_size: measure(own.reduce((sum, row) => sum + row.source_size_bytes!, 0), 3), estimated_rows: measure(own.reduce((sum, row) => sum + row.estimated_rows!, 0), 3) });
  }
  const scopedSources = (scope: OperationsScope) => sources.filter(source => (!scope.source_id || source.id === scope.source_id) && (!scope.runtime_id || source.runtime_instance_id === scope.runtime_id));
  const scopedMirrors = (scope: OperationsScope) => { const ids = new Set(scopedSources(scope).map(source => source.id)); return mirrors.filter(mirror => ids.has(mirror.source_id)); };
  const overview = (scope: OperationsScope = {}, rank = "size"): FleetOverview => {
    const selected = scopedSources(scope), rows = scopedMirrors(scope);
    const health = emptyHealth();
    const segments = { replication: emptyHealth(), production: emptyHealth(), consumption: emptyHealth(), storage: emptyHealth() };
    selected.forEach(source => { health[source.health]++; LINKS.forEach(link => { segments[link][source.segment_health[link]]++; }); });
    const state = (key: FleetState) => { const count = rows.filter(row => row.grouped_state === key).length; return { count, percent: rows.length ? count / rows.length * 100 : null }; };
    const scanning = rows.filter(row => row.progress?.scanned_bytes != null);
    const published = rows.filter(row => row.published_generation_id).length;
    return { observed_at: fleetObservedAt, source_count: selected.length, mirror_count: rows.length,
      source_size: measure(rows.reduce((sum, row) => sum + row.source_size_bytes!, 0), rows.length), estimated_rows: measure(rows.reduce((sum, row) => sum + row.estimated_rows!, 0), rows.length),
      published_count: published, published_percent: rows.length ? published / rows.length * 100 : null,
      attention_count: state("attention").count, states: { synchronizing: state("synchronizing"), copying: state("copying"), attention: state("attention"), stopped: state("stopped") },
      snapshot: { scanned_bytes: scanning.length ? scanning.reduce((sum, row) => sum + row.progress!.scanned_bytes!, 0) : null,
        source_size_bytes: scanning.length ? scanning.reduce((sum, row) => sum + row.source_size_bytes!, 0) : null,
        sampled: scanning.length, missing: 0, queued: rows.filter(row => row.status === "waiting").length },
      health, segments, ranking: [...selected].sort((a, b) => rank === "attention" ? b.attention_count - a.attention_count || a.id.localeCompare(b.id) : b.source_size.value! - a.source_size.value!).slice(0, 8), ranking_total: selected.length };
  };
  const inventory = (query: InventoryQuery): InventoryPage => {
    const q = query.q?.toLowerCase() ?? "";
    const all = scopedMirrors(query).filter(row => (!query.grouped_state || row.grouped_state === query.grouped_state)
      && (!query.published_only || row.published_generation_id != null) && (!q || `${row.qualified_table} ${row.id}`.toLowerCase().includes(q)));
    const cause_counts: InventoryPage["cause_counts"] = {};
    all.forEach(row => { if (row.attention_cause) cause_counts[row.attention_cause] = (cause_counts[row.attention_cause] ?? 0) + 1; });
    const rows = all.filter(row => !query.cause || row.attention_cause === query.cause);
    const priority = (row: InventoryMirror) => row.grouped_state === "attention" ? 0 : row.grouped_state === "copying" ? 1 : row.grouped_state === "synchronizing" ? 2 : 3;
    const triage = (row: InventoryMirror) => row.attention_cause === "pending_stop" ? 2 : row.published_generation_id ? 1 : 0;
    rows.sort((a, b) => query.sort === "table" ? a.qualified_table.localeCompare(b.qualified_table) : query.sort === "rows" ? b.estimated_rows! - a.estimated_rows! : query.sort === "size" ? b.source_size_bytes! - a.source_size_bytes!
      : priority(a) - priority(b) || (a.grouped_state === "attention" ? triage(a) - triage(b) || (a.attention_since ?? "").localeCompare(b.attention_since ?? "") : b.source_size_bytes! - a.source_size_bytes!) || a.id.localeCompare(b.id));
    return { items: rows.slice(query.offset, query.offset + query.limit), total: rows.length, limit: query.limit, offset: query.offset, cause_counts };
  };
  const sourcePage = (query: FleetSearch) => {
    const rows = scopedSources(query).filter(source => (!query.q || `${source.name} ${source.id}`.toLowerCase().includes(query.q.toLowerCase()))
      && (!query.health || (query.segment ? source.segment_health[query.segment as Link] : source.health) === query.health));
    rows.sort((a, b) => healthOrder.indexOf(query.segment ? a.segment_health[query.segment as Link] : a.health) - healthOrder.indexOf(query.segment ? b.segment_health[query.segment as Link] : b.health) || a.id.localeCompare(b.id));
    return { items: rows.slice(query.offset, query.offset + query.limit), total: rows.length, limit: query.limit, offset: query.offset };
  };
  const runtimePage = (query: FleetSearch) => {
    const selected = scopedSources(query);
    const runtimeIds = [...new Set(selected.map(source => source.runtime_instance_id!))];
    const rows: RuntimeFleet[] = runtimeIds.filter(id => !query.q || id.toLowerCase().includes(query.q.toLowerCase())).map(id => {
      const own = selected.filter(source => source.runtime_instance_id === id), health = emptyHealth();
      own.forEach(source => { health[query.segment ? source.segment_health[query.segment as Link] : source.health]++; });
      return { id, runtime_instance_id: id, source_count: own.length, affected_source_count: query.health ? health[query.health as Health] : own.length - health.healthy,
        health: healthOrder.find(state => health[state] > 0) ?? "unobserved" };
    }).filter(runtime => !query.health || runtime.affected_source_count > 0).sort((a, b) => b.affected_source_count - a.affected_source_count || a.id.localeCompare(b.id));
    return { items: rows.slice(query.offset, query.offset + query.limit), total: rows.length, limit: query.limit, offset: query.offset };
  };
  const throughput = (scope: OperationsScope = {}, hours = 6): FleetThroughput => {
    const selected = scopedSources(scope), rows = scopedMirrors(scope), end = Date.parse(fleetObservedAt), step = hours * 3_600_000 / 24;
    const rate = (value: number | null, at: number): ThroughputRate => ({ value, sampled: value == null ? 0 : rows.length, missing: value == null ? rows.length : 0,
      interval_start: value == null ? null : new Date(at - step).toISOString(), interval_end: value == null ? null : new Date(at).toISOString(),
      oldest_observation: value == null ? null : new Date(at).toISOString(), newest_observation: value == null ? null : new Date(at).toISOString(), measured_seconds: value == null ? 0 : step / 1000 });
    return { observed_at: fleetObservedAt, window_start: new Date(end - 24 * step).toISOString(), window_end: fleetObservedAt, hours, unit: "MB/s", mirror_count: rows.length, source_count: selected.length,
      points: Array.from({ length: 24 }, (_, i) => { const at = end - (23 - i) * step, value = (0.8 + Math.sin(i / 3) * 0.2) * selected.length / 10;
        return { at: new Date(at).toISOString(), bucket_start: new Date(at - step).toISOString(), received: rate(i === 6 || i === 7 ? null : i === 13 ? 0 : value, at), committed: rate(i === 7 ? null : i === 13 ? 0 : value * 0.85, at) }; }) };
  };
  return { sources, mirrors, overview, inventory, sourcePage, runtimePage, throughput };
}
