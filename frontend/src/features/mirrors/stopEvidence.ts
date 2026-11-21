import type { Mirror } from "./types";

export function getMirrorStopEvidence(mirror: Mirror) {
  if (mirror.enabled || (mirror.status !== "disabled" && mirror.status !== "disable_pending")) return null;

  const { control_revision: revision, applied_revision, observed_at, stop_ack } = mirror.control;
  if (mirror.status === "disabled" && stop_ack && applied_revision === revision
    && stop_ack.observed_at === observed_at
    && mirror.operations.some(operation => operation.id === stop_ack.operation_id
      && operation.mirror_id === mirror.id
      && operation.kind === "disable"
      && operation.state === "applied"
      && operation.control_revision === revision
      && operation.observed_evidence_refs.includes(stop_ack.source_operation_id))) {
    return { state: "confirmed", observedAt: stop_ack.observed_at } as const;
  }
  return { state: "pending" } as const;
}
