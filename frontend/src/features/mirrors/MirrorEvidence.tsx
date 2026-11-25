import { useCan, useTranslate } from "@refinedev/core";
import { Instant } from "@/components/display/Instant";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { setupHref, setupStepForReadiness } from "./setup/setupLinks";
import { getMirrorStopEvidence } from "./stopEvidence";
import type { Mirror } from "./types";

const waitReasons = new Set(["source_disabled", "capture_credential_missing", "table_unqualified", "snapshot_window_closed", "snapshot_slot_busy", "own_snapshot_slot_busy", "publication_pending", "incremental_snapshot_blocked"]);

export function readinessLabel(key: string, t: ReturnType<typeof useTranslate>) {
  const cause = /^mirror_(permission|schema|continuity)_blocked$/.exec(key)?.[1];
  if (cause) return t(`mirrors.blocker.${cause}`);
  return waitReasons.has(key) ? t(`mirrors.wait.${key}`) : key;
}

export function readinessAction(item: Mirror["readiness"][number], t: ReturnType<typeof useTranslate>) {
  const cause = /^mirror_(permission|schema|continuity)_blocked$/.exec(item.key)?.[1];
  if (cause) return t(`mirrors.next.${cause}`);
  return waitReasons.has(item.key) ? t(`mirrors.action.${item.key}`) : item.action;
}

function outstanding(mirror: Mirror) {
  return mirror.readiness.filter(item => (item.result === "fail" || item.result === "unknown")
    && !(item.key === "capture_admission" && item.result === "unknown" && !item.observed_at && !item.observed
      && (mirror.published_generation_id || mirror.progress)));
}

export function currentOpen(mirror: Mirror) {
  if (!mirror.enabled) return;
  const opens = mirror.operations.filter(operation =>
    operation.kind === "open" && operation.control_revision === mirror.control.control_revision);
  // The API returns operations oldest first, including replaced attempts in the same revision.
  return opens.findLast(operation => operation.state === "pending")
    ?? opens.findLast(operation => operation.state === "applied");
}

export function MirrorEvent({ mirror }: { mirror: Mirror }) {
  const t = useTranslate();
  const open = currentOpen(mirror);
  const op = open?.state === "pending" ? open : undefined;
  const blocker = outstanding(mirror).find(item => item.result === "fail" || item.observed_at);
  const progress = mirror.progress;
  const published = !!mirror.published_generation_id;
  const request = op && op.control_revision === 1 && mirror.operations.length === 1 ? "first" : "request";
  const stop = getMirrorStopEvidence(mirror);
  return <>
    {stop?.state === "pending" && <div>{t("mirrors.event.disableRequested")}</div>}
    {stop?.state === "confirmed" && <div>{t("mirrors.event.stopConfirmed")} · <Instant value={stop.observedAt} /></div>}
    {published && <div>{t("mirrors.event.published")}</div>}
    {published && <div>{t("mirrors.freshnessUnknown")}</div>}
    {published && op && <div>{t("mirrors.event.retained")}</div>}
    {blocker && <div>{readinessLabel(blocker.key, t)} · {t(`mirrors.result.${blocker.result}`)} {blocker.observed_at && <Instant value={blocker.observed_at} />}</div>}
    {progress && <div>{t(`mirrors.event.${progress.stage}`)} {progress.observed_at && <Instant value={progress.observed_at} />}</div>}
    {!progress && op && <div>{t(`mirrors.event.${request}`)} · {t("mirrors.requestedAt")} <Instant value={op.requested_at} /></div>}
    {!stop && !published && !progress && !op && !blocker && <div>{t("mirrors.unknownEvidence")}</div>}
  </>;
}

export function SetupStepLink({ sourceId, readinessKey }: { sourceId: string; readinessKey: string }) {
  const t = useTranslate();
  const { data } = useCan({ resource: "mirrors", action: "list" });
  const step = setupStepForReadiness(readinessKey);
  if (!data?.can || !step) return null;
  return <ConsoleLink href={setupHref(sourceId, step)}>{t("mirrorSetup.openStep")}</ConsoleLink>;
}

export function MirrorNextAction({ mirror }: { mirror: Mirror }) {
  const t = useTranslate();
  const blockers = outstanding(mirror);
  return <>{blockers.length ? blockers.map(item => <div key={item.key}>
    <div>{item.key === "capture_admission" && item.owner === "deployer" && item.action === "Qualify capture before admission"
      ? t("mirrors.confirmCapture") : readinessAction(item, t)}</div>
    <SetupStepLink sourceId={mirror.source_id} readinessKey={item.key} />
  </div>) : t("mirrors.checkLater")}</>;
}
