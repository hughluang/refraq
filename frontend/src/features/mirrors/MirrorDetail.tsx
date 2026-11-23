"use client";

import { Button, Stack, Text } from "@mantine/core";
import { useConsoleLocation, useConsoleNavigation } from "@/components/navigation/useConsoleNavigation";
import { useCan, useTranslate } from "@refinedev/core";
import { useEffect, useRef, useState } from "react";
import { DisplayField } from "@/components/display/DisplayField";
import { Instant } from "@/components/display/Instant";
import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { readinessAction, readinessLabel } from "./MirrorEvidence";
import { MirrorCopySummary, MirrorStatusFreshness } from "./MirrorCopySummary";
import { useMirrorStatus } from "./useMirrorStatus";
import { mirrorReturnHref, restoreMirrorPosition } from "./mirrorNavigation";
import { MirrorSwitch } from "./MirrorSwitch";
import { getMirrorStopEvidence } from "./stopEvidence";
import { FormSection } from "@/components/form/FormSection";
import { TextField } from "@/components/form/TextField";
import { HeaderActions } from "@/components/layout/HeaderActions";
import { PageChrome } from "@/components/layout/PageChrome";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { presentConsoleNotification } from "@/providers/notification-provider";
import { deleteMirror, requestRecovery, setMirrorEnabled } from "./api";
import { MirrorDelete } from "./MirrorDelete";
import { MirrorJournal, Receipt } from "./MirrorJournal";
import type { PendingOperation, RecoveryAction } from "./types";

function Evidence({ value }: { value: unknown }) {
  const t = useTranslate();
  if (value == null) return <Text size="sm">{t("mirrors.unknownEvidence")}</Text>;
  if (Array.isArray(value)) return <Stack gap="xs">{value.map((item, index) => <Evidence key={index} value={item} />)}</Stack>;
  if (typeof value === "object") return <Stack gap="xs">{Object.entries(value).map(([key, item]) => <DisplayField key={key} label={key} value={key.endsWith("_at") && typeof item === "string" ? <Instant value={item} /> : <Evidence value={item} />} />)}</Stack>;
  return <Text size="sm" style={{ overflowWrap: "anywhere" }}>{String(value)}</Text>;
}

export function MirrorDetail({ id }: { id: string }) {
  return <MirrorRecord key={id} id={id} />;
}

function MirrorRecord({ id }: { id: string }) {
  const t = useTranslate();
  const navigation = useConsoleNavigation();
  const { href: current, search } = useConsoleLocation();
  const origin = mirrorReturnHref(search?.get("from") ?? null);
  const originPath = new URL(origin, "http://console.local");
  let backKey = "mirrors.back";
  if (originPath.pathname.startsWith("/console/mirrors/")) backKey = "mirrors.backToWaiting";
  else if (originPath.searchParams.has("mirrorTable")) backKey = "mirrors.backToTable";
  const { data: canWrite } = useCan({ resource: "mirrors", action: "edit" });
  const live = useMirrorStatus(id);
  const { mirror, canEnable, status, refresh } = live;
  const [pending, setPending] = useState<PendingOperation | null>(null);
  const [recovery, setRecovery] = useState<{ action: RecoveryAction; epoch: string | number; revision: number } | null>(null);
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [acceptedSetting, setAcceptedSetting] = useState<{ enabled: boolean; revision: number } | null>(null);
  const enabled = acceptedSetting?.enabled ?? mirror?.enabled ?? false;
  const deleting = useRef(false);
  const deletePending = Boolean(mirror?.deletion_operation_id);
  const writePending = useRef(false);
  const pageRequest = useRef<AbortController | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    pageRequest.current = controller;
    return () => controller.abort();
  }, []);
  useEffect(() => {
    if (status === "ready") restoreMirrorPosition(current);
  }, [status, current]);
  useEffect(() => {
    if (deletePending) deleting.current = true;
    if (deleting.current && status === "notFound") navigation.replace(origin);
  }, [deletePending, status, navigation, origin]);
  useEffect(() => {
    if (!mirror || (pending && (mirror.latest_request?.operation_id === pending.operation_id ||
        mirror.operations.some(operation => operation.id === pending.operation_id)))) setPending(null);
    if (!mirror || (acceptedSetting && mirror.control.control_revision >= acceptedSetting.revision)) setAcceptedSetting(null);
    if (!mirror || mirror.deletion_operation_id || (recovery && (
        (recovery.action === "retry" && !mirror.can_retry) || recovery.epoch !== mirror.history_epoch ||
        recovery.revision !== mirror.control.control_revision))) setRecovery(null);
  }, [mirror, pending, recovery, acceptedSetting]);
  const scope = mirror ? t("mirrors.scope", { source: mirror.source_name, table: mirror.qualified_table }) : "";
  const stopPending = mirror !== null && getMirrorStopEvidence(mirror)?.state === "pending";
  async function toggle(enabled: boolean) {
    const signal = pageRequest.current?.signal;
    if (!mirror || deletePending || !canWrite?.can || (enabled && !canEnable) || submitting || writePending.current || !signal || signal.aborted) return;
    writePending.current = true;
    setSubmitting(true);
    try {
      const accepted = await setMirrorEnabled(id, enabled, signal);
      if (signal.aborted) return;
      if ("mirror" in accepted) setAcceptedSetting({ enabled: accepted.mirror.enabled, revision: accepted.mirror.control.control_revision });
      presentConsoleNotification({ type: "success", title: t("mirrors.acceptedForTable", { table: mirror.qualified_table }) });
      setPending(null);
    } catch (error) {
      if (signal.aborted) return;
      presentProblemNotification(t, error);
    } finally {
      if (!signal.aborted) {
        await refresh();
        writePending.current = false;
        setSubmitting(false);
      }
    }
  }
  async function recover() {
    const signal = pageRequest.current?.signal;
    if (!signal || signal.aborted || !mirror || deletePending || !recovery || !canWrite?.can || submitting || writePending.current ||
      (recovery.action === "retry" ? !mirror.can_retry : !reason.trim())) return;
    writePending.current = true;
    setSubmitting(true);
    try {
      const result = await requestRecovery(id, {
        action: recovery.action, expected_history_epoch: recovery.epoch, ...(reason.trim() ? { reason: reason.trim() } : {}),
        ...(recovery.action === "retry" ? { expected_control_revision: recovery.revision } : {}),
      });
      if (signal.aborted) return;
      setPending(result);
      setRecovery(null);
      presentConsoleNotification({ type: "success", title: t("mirrors.acceptedForTable", { table: mirror.qualified_table }) });
    } catch (error) {
      if (signal.aborted) return;
      setRecovery(null);
      presentProblemNotification(t, error);
    } finally {
      if (!signal.aborted) {
        await refresh();
        writePending.current = false;
        setSubmitting(false);
      }
    }
  }
  const originDescription = mirror ? t("mirrors.sourceToStorage", {
    source: mirror.source_name,
    destination: mirror.storage_destination,
    size: mirror.source_size_bytes == null ? t("mirrors.unmeasured") : t("mirrors.bytes", { bytes: mirror.source_size_bytes.toLocaleString() }),
  }) : undefined;
  return <PageChrome title={mirror?.qualified_table ?? t("mirrors.title")} status={status}
    description={originDescription} onRetry={() => void refresh()}
    titleExtra={mirror && <Text size="sm">{t(`mirrors.status.${stopPending ? "disable_pending" : mirror.status}`)}</Text>}
    actions={<HeaderActions navigation={<>
      <Button component={ConsoleLink} href={origin} size="sm" variant="light">{t(backKey)}</Button>
      <Button size="sm" variant="light" disabled={submitting} onClick={() => void refresh()}>{t("common.refresh")}</Button>
    </>}
      standard={mirror && canWrite?.can && <MirrorDelete key={mirror.control.control_revision} table={mirror.qualified_table}
        source={mirror.source_name} generation={mirror.published_generation_id} enabled={enabled}
        pending={deletePending} disabled={submitting || acceptedSetting !== null}
        remove={signal => deleteMirror(id, mirror.control.control_revision, signal)}
        onResult={stillPending => {
          if (stillPending) { deleting.current = true; void refresh(); }
          else navigation.replace(origin);
        }} />} />}>
    {mirror ? <Stack gap="lg">
      <MirrorStatusFreshness {...live} />
      {deletePending && <Text role="status">{t("mirrors.deletePending", { table: mirror.qualified_table })}</Text>}
      <FormSection title={t("mirrors.synchronization")} columns={1}>
        <MirrorSwitch enabled={enabled}
          disabled={deletePending || submitting || !canWrite?.can || (!enabled && !canEnable)}
          table={mirror.qualified_table} onChange={enabled => void toggle(enabled)} />
        {!deletePending && !enabled && canWrite?.can && <Text size="sm">{t("mirrors.resumePlan")}</Text>}
      </FormSection>
      <MirrorCopySummary mirror={mirror} origin={current} />
      {pending && mirror.latest_request?.operation_id !== pending.operation_id &&
        <DisplayField label={t("mirrors.operation")} value={`${pending.operation_id}: ${t("mirrors.pending")}`} />}
      <MirrorJournal key={mirror.journal?.next_cursor} mirror={mirror} />
      <details>
        <summary>{t("mirrors.requestsAndReceipts")}</summary>
        <Stack gap="md" mt="md">
          <FormSection title={t("mirrors.receiptSummary")}>
            <DisplayField label={t("mirrors.latestRequest")} value={<Receipt event={mirror.latest_request} />} />
            <DisplayField label={t("mirrors.latestObservation")} value={<Receipt event={mirror.latest_observation} />} />
            <DisplayField label={t("mirrors.continuity")} value={<Receipt event={mirror.continuity_check} />} />
            <DisplayField label={t("mirrors.allocatedGeneration")} value={mirror.allocated_generation_id} />
            <DisplayField label={t("mirrors.publishedAt")} value={<Instant value={mirror.published_at} />} />
            {mirror.snapshot_slot_holder && <DisplayField label={t("mirrors.wait.snapshot_slot_busy")} value={mirror.snapshot_slot_holder.qualified_table} />}
            {mirror.publication_wait && <DisplayField label={t("mirrors.wait.publication_pending")} value={mirror.publication_wait.qualified_table} />}
          </FormSection>
          <FormSection title={t("mirrors.identity")}>
            <DisplayField label={t("mirrors.rowEstimate")} value={mirror.estimated_rows?.toLocaleString() ?? t("mirrors.unmeasured")} />
            <DisplayField label={t("mirrors.generation")} value={mirror.published_generation_id} />
            <DisplayField label={t("mirrors.captureGeneration")} value={mirror.capture_generation} />
            <DisplayField label={t("mirrors.epoch")} value={mirror.history_epoch} />
          </FormSection>
          <FormSection title={t("mirrors.readiness")} description={t("mirrors.readinessHelp")} columns={1}>
            {mirror.readiness.length ? mirror.readiness.map(item => <FormSection key={item.key} title={readinessLabel(item.key, t)}>
              <DisplayField label={t("mirrors.result")} value={t(`mirrors.result.${item.result}`)} />
              <DisplayField label={t("mirrors.observedAt")} value={<Instant value={item.observed_at} />} />
              <DisplayField label={t("mirrors.expected")} value={<Evidence value={item.expected} />} />
              <DisplayField label={t("mirrors.observed")} value={<Evidence value={item.observed} />} />
              <DisplayField label={t("mirrors.owner")} value={item.owner} />
              <DisplayField label={t("mirrors.remediation")} value={readinessAction(item, t)} />
            </FormSection>) : <Text>{t("mirrors.unknownEvidence")}</Text>}
          </FormSection>
          {(["profile", "control", "progress", "fault", "operations"] as const).map(key => <FormSection key={key} title={t(`mirrors.${key}`)} columns={1}><Evidence value={mirror[key]} /></FormSection>)}
          <FormSection title={t("mirrors.bounds")}><DisplayField label={t("mirrors.lower")} value={<Evidence value={mirror.retained_lower_bound} />} /><DisplayField label={t("mirrors.upper")} value={<Evidence value={mirror.committed_upper_bound} />} /></FormSection>
        </Stack>
      </details>
      {canWrite?.can && !deletePending && <FormSection title={t("mirrors.controls")}>
        {(["retry", "run_now", "postpone", "manual"] as const).filter(action => action !== "retry" || mirror.can_retry)
          .map(action => <Button key={action} size="sm" variant="light" disabled={submitting || mirror.history_epoch == null} onClick={() => { if (mirror.history_epoch == null) return; setReason(""); setRecovery({ action, epoch: mirror.history_epoch, revision: mirror.control.control_revision }); }}>{t(`mirrors.recovery.${action}`)}</Button>)}
      </FormSection>}
    </Stack> : null}
    <ConfirmActionModal opened={!!mirror && !!canWrite?.can && recovery !== null} onClose={() => { if (!submitting) setRecovery(null); }} title={t(`mirrors.recovery.${recovery?.action ?? "retry"}`)} body={`${scope} ${t(`mirrors.impact.${recovery?.action ?? "retry"}`)}`} loading={submitting}
      confirmDisabled={recovery?.action !== "retry" && !reason.trim()} onConfirm={() => void recover()}>
      <DisplayField label={t("mirrors.epoch")} value={recovery?.epoch} />
      <TextField editable label={t("mirrors.reason")} required={recovery?.action !== "retry"} value={reason} onChange={event => setReason(event.currentTarget.value)} />
    </ConfirmActionModal>
  </PageChrome>;
}
