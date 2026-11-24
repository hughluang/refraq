import { apiClient } from "@/lib/api";
import type { OffsetPage } from "@/lib/pagination";
import type { JournalPage, Mirror, MirrorDetail, PendingOperation, RecoveryRequest } from "./types";
import type { FleetOverview, FleetSearch, FleetThroughput, InventoryPage, InventoryQuery, OperationsScope, RuntimeFleet, SourceFleet } from "./fleetTypes";

export function getMirror(id: string, signal?: AbortSignal) {
  return apiClient<{ mirror: MirrorDetail; can_enable: boolean }>(`/mirrors/${encodeURIComponent(id)}`, { signal });
}

export function getJournalPage(id: string, before: string, signal: AbortSignal) {
  const query = new URLSearchParams({ before, limit: "12" });
  return apiClient<JournalPage>(`/mirrors/${encodeURIComponent(id)}/journal?${query}`, { signal });
}

export function deleteMirror(id: string, revision: number, signal: AbortSignal) {
  return apiClient<PendingOperation | undefined>(
    `/mirrors/${encodeURIComponent(id)}?expected_control_revision=${revision}`, { method: "DELETE", signal },
  );
}

export function setMirrorEnabled(id: string, enabled: boolean, signal?: AbortSignal) {
  return apiClient<{ mirror: Mirror; operation_id: string } | { enabled: boolean; operation_id: string }>(`/mirrors/${encodeURIComponent(id)}`, {
    method: "PATCH", signal, headers: { "content-type": "application/json" }, body: JSON.stringify({ enabled }),
  });
}

export function requestRecovery(id: string, request: RecoveryRequest) {
  return apiClient<PendingOperation>(`/mirrors/${encodeURIComponent(id)}/recovery-requests`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(request),
  });
}

export function getMirrorMeasurements(id: string, signal: AbortSignal) {
  return apiClient<import("./diagnosticTypes").Measurements>(`/mirrors/${encodeURIComponent(id)}/measurements`, { signal });
}

export function getSourceDiagnostics(query: URLSearchParams, signal: AbortSignal) {
  return apiClient<import("./diagnosticTypes").Diagnostics>(`/mirror-diagnostics?${query}`, { signal });
}

function fleetQuery(params: object) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) if (value !== undefined && value !== null && value !== "") query.set(key, String(value));
  return query;
}

export function getFleetOverview(scope: OperationsScope & { rank?: string }, signal: AbortSignal) {
  return apiClient<FleetOverview>(`/mirror-fleet?${fleetQuery(scope)}`, { signal });
}

export function listFleetSources(params: FleetSearch, signal?: AbortSignal) {
  return apiClient<OffsetPage<SourceFleet>>(`/mirror-fleet/sources?${fleetQuery(params)}`, { signal });
}

export function listFleetRuntimes(params: FleetSearch, signal?: AbortSignal) {
  return apiClient<OffsetPage<RuntimeFleet>>(`/mirror-fleet/runtimes?${fleetQuery(params)}`, { signal });
}

export function listMirrorInventory(params: InventoryQuery) {
  return apiClient<InventoryPage>(`/mirrors?${fleetQuery(params)}`);
}

export function getFleetThroughput(params: OperationsScope & { hours: number }, signal: AbortSignal) {
  return apiClient<FleetThroughput>(`/mirror-throughput?${fleetQuery(params)}`, { signal });
}
