import { useTranslate } from "@refinedev/core";
import { Instant } from "@/components/display/Instant";
import { getMirrorStopEvidence } from "./stopEvidence";
import type { Mirror } from "./types";

const waitReasons = new Set(["source_disabled", "capture_credential_missing", "table_unqualified", "snapshot_window_closed"]);

export function readinessLabel(key: string, t: ReturnType<typeof useTranslate>) {
  return waitReasons.has(key) ? t(`mirrors.wait.${key}`) : key;
}

export function readinessAction(item: Mirror["readiness"][number], t: ReturnType<typeof useTranslate>) {
  return waitReasons.has(item.key) ? t(`mirrors.action.${item.key}`) : item.action;
}

function outstanding(mirror: Mirror) {
  return mirror.readiness.filter(item => (item.result === "fail" || item.result === "unknown")
    && !(item.key === "capture_admission" && item.result === "unknown" && !item.observed_at && !item.observed
      && (mirror.published_generation_id || mirror.progress)));
}

export function MirrorEvent({ mirror }: { mirror: Mirror }) {
  const t = useTranslate();
  const op = mirror.enabled && mirror.operations.find(item => item.kind === "open" && item.state === "pending"
    && item.control_revision === mirror.control.control_revision);
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
    {published && op && <div>{t("mirrors.event.replacement")}</div>}
    {blocker && <div>{readinessLabel(blocker.key, t)} · {t(`mirrors.result.${blocker.result}`)} {blocker.observed_at && <Instant value={blocker.observed_at} />}</div>}
    {progress && <div>{t(`mirrors.event.${progress.stage}`)} {progress.observed_at && <Instant value={progress.observed_at} />}</div>}
    {!progress && op && <div>{t(`mirrors.event.${request}`)} · {t("mirrors.requestedAt")} <Instant value={op.requested_at} /></div>}
    {!stop && !published && !progress && !op && !blocker && <div>{t("mirrors.unknownEvidence")}</div>}
  </>;
}

export function MirrorNextAction({ mirror }: { mirror: Mirror }) {
  const t = useTranslate();
  const blockers = outstanding(mirror);
  return <>{blockers.length ? blockers.map(item => <div key={item.key}>{item.key === "capture_admission" && item.owner === "deployer" && item.action === "Qualify capture before admission"
      ? t("mirrors.confirmCapture") : readinessAction(item, t)}</div>)
    : t("mirrors.checkLater")}</>;
}
