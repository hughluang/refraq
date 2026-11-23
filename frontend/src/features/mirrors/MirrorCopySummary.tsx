"use client";

import { Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { formatDurationMs } from "@/lib/datetime";
import { StatusBadge } from "@/components/display/StatusBadge";
import { DisplayField } from "@/components/display/DisplayField";
import { Instant } from "@/components/display/Instant";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { currentOpen, MirrorEvent, MirrorNextAction } from "./MirrorEvidence";
import { mirrorDetailHref, rememberMirrorPosition } from "./mirrorNavigation";
import { getMirrorStopEvidence } from "./stopEvidence";
import type { MirrorDetail, MirrorReference } from "./types";
import styles from "./MirrorCopySummary.module.css";

export function MirrorStatusFreshness({ stale, lastSuccessAt, refresh }: {
  stale: boolean; lastSuccessAt: string | null; refresh: () => Promise<void>;
}) {
  return stale ? <StatusBadge tone="warning" labelKey="mirrors.refreshStale"
    freshness={{ updatedAt: lastSuccessAt, onRefresh: () => void refresh() }} /> : null;
}

export function MirrorWaitDependency({ dependency, origin, kind }: {
  dependency: MirrorReference; origin: string; kind: "slot" | "publication";
}) {
  const t = useTranslate();
  return <DisplayField label={t(kind === "slot" ? "mirrors.wait.snapshot_slot_busy" : "mirrors.wait.publication_pending")} value={
    <ConsoleLink data-mirror-return={kind === "slot" ? "holder" : "publication"}
      onClick={event => rememberMirrorPosition(origin, event.currentTarget)}
      href={mirrorDetailHref(dependency.mirror_id, origin)}>{dependency.qualified_table}</ConsoleLink>
  } />;
}

function CopyPath({ mirror, open }: { mirror: MirrorDetail; open: ReturnType<typeof currentOpen> }) {
  const t = useTranslate();
  const stop = getMirrorStopEvidence(mirror);
  if (!open && !stop) return null;
  const stages = stop ? ["stopRequest", "stopReceipt"] : ["admission", "scan", "catchup", "publish"];
  let current = 0;
  if (stop) current = stop.state === "confirmed" ? stages.length : 1;
  else if (open?.state === "applied" && mirror.published_generation_id) current = stages.length;
  else if (mirror.progress) current = mirror.progress.stage === "catching_up" ? 2 : 1;
  const delays = ["snapshot_slot_busy", "own_snapshot_slot_busy", "snapshot_window_closed", "publication_pending"];
  const queued = mirror.readiness.some(item => delays.includes(item.key) && item.result === "fail") ||
    Boolean(mirror.publication_wait || mirror.snapshot_slot_holder);
  const admitted = mirror.readiness.some(item => item.key === "capture_admission" && item.result === "pass");
  const blocked = mirror.readiness.some(item => !delays.includes(item.key) && item.result === "fail");
  if (current === 0 && admitted) current = 1;
  const label = stop ? "mirrors.stopPath" : open?.state === "pending" && mirror.published_generation_id
    ? "mirrors.replacementPath" : "mirrors.firstCopyPath";
  return <div>
    <h3 className={styles.label}>{t(label)}</h3>
    <ol aria-label={t(label)} className={styles.path}>
      {stages.map((stage, index) => {
        const active = index === current;
        let phase = "later";
        if (index < current) phase = "complete";
        if (active) {
          phase = "current";
          if (!stop && (queued || admitted) && !mirror.progress) phase = "queued";
          if (!stop && blocked) phase = "blocked";
        }
        return <li key={stage} data-phase={phase} aria-current={active ? "step" : undefined}>
          <span className={styles.stage}>{t(`mirrors.phase.${stage}`)}</span>
          <small>{t(`mirrors.phase.${phase}`)}</small>
        </li>;
      })}
    </ol>
  </div>;
}

function ScanProgress({ progress }: { progress: MirrorDetail["progress"] }) {
  const t = useTranslate();
  const percent = progress?.scan_percent;
  return <div className={styles.measurement}>
    <h3 className={styles.label}>{t("mirrors.scanProgress")}</h3>
    <Text size="sm">{percent == null ? t("mirrors.scanPercentUnavailable") : `${Number(percent.toFixed(2))}%`}</Text>
    {percent != null && <progress aria-label={t("mirrors.scanProgress")} value={percent} max={100} />}
    {progress?.scanned_bytes == null ? <Text size="sm" c="dimmed">{t("mirrors.scanBytesUnavailable")}</Text> : <>
      <Text size="sm">{t("mirrors.scannedBytes", { bytes: progress.scanned_bytes.toLocaleString() })}</Text>
      <Text size="sm" c="dimmed">{t("mirrors.bytesObservedAt")} · {progress.bytes_observed_at
        ? <Instant value={progress.bytes_observed_at} /> : t("mirrors.unknownEvidence")}</Text>
    </>}
  </div>;
}

export function MirrorCopySummary({ mirror, origin }: { mirror: MirrorDetail; origin: string }) {
  const t = useTranslate();
  const open = currentOpen(mirror);
  const holder = mirror.snapshot_slot_holder;
  const published = Boolean(mirror.published_generation_id);
  const copying = open?.state === "pending";
  const operatorOpen = mirror.enabled ? mirror.open_request : null;
  const retainedCheck = operatorOpen?.outcome === "awaiting_continuity";
  const blocker = mirror.blocker;
  return <div className={styles.summary}>
    <div className={styles.overview}>
      {retainedCheck ? <div><h3 className={styles.label}>{t("mirrors.continuity")}</h3>
        <Text size="sm">{t("mirrors.journal.awaiting_continuity")}</Text>
      </div> : <CopyPath mirror={mirror} open={open} />}
      <div aria-live="polite" className={styles.copy} data-published={published}>
        <h3 className={styles.label}>{t("mirrors.copyAvailability")}</h3>
        <strong>{t(!published ? "mirrors.noCopy" : copying || !mirror.enabled ? "mirrors.retainedCopy" : "mirrors.readableCopy")}</strong>
      </div>
    </div>
    {holder && (holder.mirror_id === mirror.id
      ? <Text size="sm">{t("mirrors.ownSlot")}</Text>
      : <MirrorWaitDependency kind="slot" dependency={holder} origin={origin} />)}
    {mirror.publication_wait && <MirrorWaitDependency kind="publication" dependency={mirror.publication_wait} origin={origin} />}
    {blocker && <div role="status">
      <h3 className={styles.label}>{t(`mirrors.blocker.${blocker.cause}`)}</h3>
      <Text size="sm">{t("mirrors.blockedFor", { duration: formatDurationMs(Date.now() - Date.parse(blocker.since)) })}</Text>
      <Text size="sm">{t("mirrors.lastCheck")} · <Instant value={blocker.last_checked_at} /></Text>
      <Text size="sm">{t(`mirrors.next.${blocker.cause}`)}</Text>
    </div>}
    {copying && !retainedCheck && <ScanProgress progress={mirror.progress} />}
    <DisplayField label={t("mirrors.lastEvent")} value={<MirrorEvent mirror={mirror} />} />
    {(operatorOpen || open) && <DisplayField label={t("mirrors.openRequest")} value={<Stack gap={2}>
      <Text size="sm">{t(operatorOpen?.outcome ? `mirrors.journal.${operatorOpen.outcome}` : copying ? "mirrors.awaitingPublication" : "mirrors.openApplied")}</Text>
      <Text size="sm" c="dimmed">{operatorOpen?.operation_id ?? open?.id}</Text>
    </Stack>} />}
    {mirror.enabled && <DisplayField label={t("mirrors.nextAction")} value={<MirrorNextAction mirror={mirror} />} />}
  </div>;
}
