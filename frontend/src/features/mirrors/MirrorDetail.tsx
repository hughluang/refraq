"use client";

import { Button, Stack, Text } from "@mantine/core";
import { useCan, useTranslate } from "@refinedev/core";
import { useCallback, useEffect, useRef, useState } from "react";
import { DisplayField } from "@/components/display/DisplayField";
import { Instant } from "@/components/display/Instant";
import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { MirrorEvent, MirrorNextAction, readinessAction, readinessLabel } from "./MirrorEvidence";
import { MirrorSwitch } from "./MirrorSwitch";
import { getMirrorStopEvidence } from "./stopEvidence";
import { FormSection } from "@/components/form/FormSection";
import { TextField } from "@/components/form/TextField";
import { HeaderActions } from "@/components/layout/HeaderActions";
import { PageChrome } from "@/components/layout/PageChrome";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { ApiError } from "@/lib/api";
import { getMirror, requestRecovery, setMirrorEnabled } from "./api";
import type { Mirror, PendingOperation, RecoveryAction } from "./types";

function Evidence({ value }: { value: unknown }) {
  const t = useTranslate();
  if (value == null) return <Text size="sm">{t("mirrors.unknownEvidence")}</Text>;
  if (Array.isArray(value)) return <Stack gap="xs">{value.map((item, index) => <Evidence key={index} value={item} />)}</Stack>;
  if (typeof value === "object") return <Stack gap="xs">{Object.entries(value).map(([key, item]) => <DisplayField key={key} label={key} value={(key === "observed_at" || key === "requested_at") && typeof item === "string" ? <Instant value={item} /> : <Evidence value={item} />} />)}</Stack>;
  return <Text size="sm" style={{ overflowWrap: "anywhere" }}>{String(value)}</Text>;
}

export function MirrorDetail({ id }: { id: string }) {
  return <MirrorRecord key={id} id={id} />;
}

function MirrorRecord({ id }: { id: string }) {
  const t = useTranslate();
  const { data: canWrite } = useCan({ resource: "mirrors", action: "edit" });
  const [canEnable, setCanEnable] = useState(false);
  const [mirror, setMirror] = useState<Mirror | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "unloaded" | "forbidden" | "notFound">("loading");
  const [pending, setPending] = useState<PendingOperation | null>(null);
  const [recovery, setRecovery] = useState<{ action: RecoveryAction; epoch: string | number } | null>(null);
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const writePending = useRef(false);
  const pageRequest = useRef<AbortController | null>(null);
  const loadRevision = useRef(0);
  const load = useCallback(async (signal?: AbortSignal) => {
    const revision = ++loadRevision.current;
    try {
      const result = await getMirror(id, signal);
      if (signal?.aborted || loadRevision.current !== revision) return;
      setMirror(result.mirror);
      setCanEnable(result.can_enable);
      setStatus("ready");
    } catch (error) {
      if (signal?.aborted || loadRevision.current !== revision) return;
      setMirror(null);
      setRecovery(null);
      setPending(null);
      setStatus(error instanceof ApiError && error.status === 404 ? "notFound" : error instanceof ApiError && error.status === 403 ? "forbidden" : "unloaded");
      presentProblemNotification(t, error);
    }
  }, [id, t]);
  useEffect(() => {
    const controller = new AbortController();
    pageRequest.current = controller;
    setMirror(null);
    setStatus("loading");
    setPending(null);
    void load(controller.signal);
    return () => { loadRevision.current++; controller.abort(); };
  }, [load]);

  const scope = mirror ? t("mirrors.scope", { source: mirror.source_name ?? mirror.source_id, table: mirror.qualified_table }) : "";
  const stopPending = mirror !== null && getMirrorStopEvidence(mirror)?.state === "pending";
  async function toggle(enabled: boolean) {
    const signal = pageRequest.current?.signal;
    if (!mirror || !canWrite?.can || (enabled && !canEnable) || submitting || writePending.current || !signal || signal.aborted) return;
    writePending.current = true;
    setSubmitting(true);
    try {
      ++loadRevision.current;
      const result = await setMirrorEnabled(id, enabled, signal);
      if (signal.aborted) return;
      setMirror(result.mirror);
      setPending(null);
    } catch (error) {
      if (signal.aborted) return;
      presentProblemNotification(t, error);
    } finally {
      if (!signal.aborted) {
        await load(signal);
        writePending.current = false;
        setSubmitting(false);
      }
    }
  }
  async function recover() {
    if (!mirror || !recovery || !canWrite?.can || submitting || (recovery.action !== "retry" && !reason.trim())) return;
    setSubmitting(true);
    try {
      const result = await requestRecovery(id, {
        action: recovery.action, expected_history_epoch: recovery.epoch, ...(reason.trim() ? { reason: reason.trim() } : {}),
      });
      setPending(result);
      setRecovery(null);
      await load();
    } catch (error) {
      presentProblemNotification(t, error);
      await load();
    } finally { setSubmitting(false); }
  }
  return <PageChrome title={mirror?.qualified_table ?? t("mirrors.title")} status={status} onRetry={() => void load()}
    actions={<HeaderActions navigation={<><Button component={ConsoleLink} href="/console/mirrors" size="sm" variant="light">{t("mirrors.back")}</Button><Button size="sm" variant="light" disabled={submitting} onClick={() => void load()}>{t("common.refresh")}</Button></>}
      />}>
    {mirror ? <Stack gap="xl">
      <FormSection title={t("mirrors.lastEvent")}>
        <MirrorEvent mirror={mirror} />
        <DisplayField label={t("mirrors.nextAction")} value={<MirrorNextAction mirror={mirror} />} />
      </FormSection>
      <FormSection title={t("mirrors.identity")}>
        <DisplayField label={t("mirrors.source")} value={mirror.source_name ?? mirror.source_key ?? mirror.source_id} />
        <DisplayField label={t("mirrors.object")} value={mirror.qualified_table} />
        <MirrorSwitch
          enabled={mirror.enabled}
          disabled={submitting || !canWrite?.can || (!mirror.enabled && !canEnable)}
          table={mirror.qualified_table}
          onChange={enabled => void toggle(enabled)}
        />
        <DisplayField label={t("mirrors.status")} value={t(`mirrors.status.${stopPending ? "disable_pending" : mirror.status}`)} helper={t("mirrors.intentOnly")} />
        <DisplayField label={t("mirrors.generation")} value={mirror.published_generation_id} />
        <DisplayField label={t("mirrors.captureGeneration")} value={mirror.capture_generation} />
        <DisplayField label={t("mirrors.epoch")} value={mirror.history_epoch} />
        <DisplayField label={t("mirrors.operation")} value={pending ? `${pending.operation_id}: ${t("mirrors.pending")}` : null} />
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
      {canWrite?.can && <FormSection title={t("mirrors.controls")}>
        {(["retry", "run_now", "postpone", "manual"] as const).map(action => <Button key={action} size="sm" variant="light" disabled={submitting || mirror.history_epoch == null} onClick={() => { if (mirror.history_epoch == null) return; setReason(""); setRecovery({ action, epoch: mirror.history_epoch }); }}>{t(`mirrors.recovery.${action}`)}</Button>)}
      </FormSection>}
    </Stack> : null}
    <ConfirmActionModal opened={!!mirror && !!canWrite?.can && recovery !== null} onClose={() => { if (!submitting) setRecovery(null); }} title={t(`mirrors.recovery.${recovery?.action ?? "retry"}`)} body={`${scope} ${t(`mirrors.impact.${recovery?.action ?? "retry"}`)}`} loading={submitting}
      confirmDisabled={recovery?.action !== "retry" && !reason.trim()} onConfirm={() => void recover()}>
      <DisplayField label={t("mirrors.epoch")} value={recovery?.epoch} />
      <TextField editable label={t("mirrors.reason")} required={recovery?.action !== "retry"} value={reason} onChange={event => setReason(event.currentTarget.value)} />
    </ConfirmActionModal>
  </PageChrome>;
}
