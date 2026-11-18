"use client";

import { Button, Stack, Text } from "@mantine/core";
import { useCan, useTranslate } from "@refinedev/core";
import { useCallback, useEffect, useState } from "react";
import { DisplayField } from "@/components/display/DisplayField";
import { Instant } from "@/components/display/Instant";
import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { useConsoleMutation } from "@/components/feedback/useConsoleMutation";
import { FormSection } from "@/components/form/FormSection";
import { TextField } from "@/components/form/TextField";
import { NumberField } from "@/components/form/NumberField";
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
  if (typeof value === "object") return <Stack gap="xs">{Object.entries(value).map(([key, item]) => <DisplayField key={key} label={key} value={key === "observed_at" && typeof item === "string" ? <Instant value={item} /> : <Evidence value={item} />} />)}</Stack>;
  return <Text size="sm" style={{ overflowWrap: "anywhere" }}>{String(value)}</Text>;
}

export function MirrorDetail({ id }: { id: string }) {
  const t = useTranslate();
  const { data: canWrite } = useCan({ resource: "mirrors", action: "edit" });
  const mutation = useConsoleMutation();
  const [mirror, setMirror] = useState<Mirror | null>(null);
  const [status, setStatus] = useState<"loading" | "ready" | "unloaded" | "forbidden" | "notFound">("loading");
  const [pending, setPending] = useState<PendingOperation | null>(null);
  const [recovery, setRecovery] = useState<{ action: RecoveryAction; epoch: string | number } | null>(null);
  const [reason, setReason] = useState("");
  const [channelId, setChannelId] = useState("");
  const [channelVersion, setChannelVersion] = useState<number | string>("");
  const [submitting, setSubmitting] = useState(false);
  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const result = await getMirror(id, signal);
      if (signal?.aborted) return;
      setMirror(result.mirror);
      setStatus("ready");
    } catch (error) {
      if (signal?.aborted) return;
      setStatus(error instanceof ApiError && error.status === 404 ? "notFound" : error instanceof ApiError && error.status === 403 ? "forbidden" : "unloaded");
      presentProblemNotification(t, error);
    }
  }, [id, t]);
  useEffect(() => {
    const controller = new AbortController();
    setMirror(null);
    setStatus("loading");
    setPending(null);
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  function toggle() {
    if (!mirror || !canWrite?.can) return;
    mutation.run({
      safety: "confirm", recordName: mirror.qualified_table,
      consequence: t("mirrors.intentOnly"), outcome: t("mirrors.accepted"),
      execute: async () => {
        const result = await setMirrorEnabled(id, !mirror.enabled);
        setMirror(result.mirror);
        setPending({ operation_id: result.operation_id, state: "pending" });
      },
    });
  }
  async function recover() {
    if (!mirror || !recovery || !canWrite?.can || submitting || !reason.trim()) return;
    if (recovery.action === "reconcile_state" && (!channelId.trim() || !Number.isInteger(channelVersion) || Number(channelVersion) < 1)) return;
    setSubmitting(true);
    try {
      const result = await requestRecovery(id, {
        action: recovery.action, expected_history_epoch: recovery.epoch, reason: reason.trim(),
        ...(recovery.action === "reconcile_state" ? { channel_id: channelId.trim(), channel_version: Number(channelVersion) } : {}),
      });
      setPending(result);
      setRecovery(null);
      await load();
    } catch (error) {
      presentProblemNotification(t, error);
    } finally { setSubmitting(false); }
  }
  return <PageChrome title={mirror?.qualified_table ?? t("mirrors.title")} status={status} onRetry={() => void load()}
    actions={<HeaderActions navigation={<><Button component={ConsoleLink} href="/console/mirrors" size="sm" variant="light">{t("mirrors.back")}</Button><Button size="sm" variant="light" onClick={() => void load()}>{t("common.refresh")}</Button></>}
      lifecycle={mirror && status === "ready" && canWrite?.can ? <>
        <Button size="sm" variant="light" loading={mutation.submitting} disabled={mirror.status === "disable_pending"} onClick={toggle}>{t(mirror.enabled ? "mirrors.disable" : "mirrors.enable")}</Button>
        {(["retry", "run_now", "postpone", "manual", "reconcile_state"] as const).map(action => <Button key={action} size="sm" variant="light" disabled={mutation.submitting || submitting || mirror.history_epoch == null} onClick={() => { if (mirror.history_epoch == null) return; setReason(""); setChannelId(""); setChannelVersion(""); setRecovery({ action, epoch: mirror.history_epoch }); }}>{t(`mirrors.recovery.${action}`)}</Button>)}
      </> : null} />}>
    {mirror ? <Stack gap="xl">
      <FormSection title={t("mirrors.identity")}>
        <DisplayField label={t("mirrors.source")} value={mirror.source_key ?? mirror.source_id} />
        <DisplayField label={t("mirrors.object")} value={mirror.qualified_table} />
        <DisplayField label={t("mirrors.status")} value={t(`mirrors.status.${mirror.status}`)} helper={t("mirrors.intentOnly")} />
        <DisplayField label={t("mirrors.generation")} value={mirror.published_generation_id} />
        <DisplayField label={t("mirrors.captureGeneration")} value={mirror.capture_generation} />
        <DisplayField label={t("mirrors.epoch")} value={mirror.history_epoch} />
        <DisplayField label={t("mirrors.references")} value={mirror.published_reference_count} />
        <DisplayField label={t("mirrors.operation")} value={pending ? `${pending.operation_id}: ${t("mirrors.pending")}` : null} />
      </FormSection>
      <FormSection title={t("mirrors.readiness")} description={t("mirrors.readinessHelp")} columns={1}>
        {mirror.readiness.length ? mirror.readiness.map(item => <FormSection key={item.key} title={item.key}>
          <DisplayField label={t("mirrors.result")} value={t(`mirrors.result.${item.result}`)} />
          <DisplayField label={t("mirrors.observedAt")} value={<Instant value={item.observed_at} />} />
          <DisplayField label={t("mirrors.expected")} value={<Evidence value={item.expected} />} />
          <DisplayField label={t("mirrors.observed")} value={<Evidence value={item.observed} />} />
          <DisplayField label={t("mirrors.owner")} value={item.owner} />
          <DisplayField label={t("mirrors.remediation")} value={item.action} />
        </FormSection>) : <Text>{t("mirrors.unknownEvidence")}</Text>}
      </FormSection>
      {(["profile", "control", "progress", "fault", "operations"] as const).map(key => <FormSection key={key} title={t(`mirrors.${key}`)} columns={1}><Evidence value={mirror[key]} /></FormSection>)}
      <FormSection title={t("mirrors.bounds")}><DisplayField label={t("mirrors.lower")} value={<Evidence value={mirror.retained_lower_bound} />} /><DisplayField label={t("mirrors.upper")} value={<Evidence value={mirror.committed_upper_bound} />} /></FormSection>
    </Stack> : null}
    {mutation.dialog}
    <ConfirmActionModal opened={recovery !== null} onClose={() => { if (!submitting) setRecovery(null); }} title={t(`mirrors.recovery.${recovery?.action ?? "retry"}`)} body={t("mirrors.recoveryHelp")} loading={submitting}
      confirmDisabled={!reason.trim() || (recovery?.action === "reconcile_state" && (!channelId.trim() || !Number.isInteger(channelVersion) || Number(channelVersion) < 1))} onConfirm={() => void recover()}>
      <DisplayField label={t("mirrors.epoch")} value={recovery?.epoch} />
      <TextField editable label={t("mirrors.reason")} required value={reason} onChange={event => setReason(event.currentTarget.value)} />
      {recovery?.action === "reconcile_state" ? <><TextField editable label={t("mirrors.channelId")} required value={channelId} onChange={event => setChannelId(event.currentTarget.value)} /><NumberField editable label={t("mirrors.channelVersion")} required min={1} allowDecimal={false} value={channelVersion} onChange={setChannelVersion} /></> : null}
    </ConfirmActionModal>
  </PageChrome>;
}
