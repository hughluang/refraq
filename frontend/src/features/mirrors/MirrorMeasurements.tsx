"use client";

import { Button, Group, Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect } from "react";
import { DisplayField } from "@/components/display/DisplayField";
import { Instant } from "@/components/display/Instant";
import { FormSection } from "@/components/form/FormSection";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { getMirrorMeasurements } from "./api";
import type { Measurements } from "./diagnosticTypes";
import { rememberMirrorPosition, restoreMirrorPosition } from "./mirrorNavigation";
import { useDiagnosticRead } from "./useDiagnosticRead";
import "./diagnostics.css";

export function Comparison({ values }: { values: { label: string; value: number | null }[] }) {
  const t = useTranslate();
  const max = Math.max(1, ...values.map(row => row.value ?? 0));
  return <div className="diagnostic-comparison">
    {values.map(row => <div key={row.label} className="diagnostic-comparison-row">
      <Text size="sm">{row.label}</Text>
      <div className="diagnostic-bar-track" aria-hidden="true"><div className="diagnostic-bar" style={{ width: `${(row.value ?? 0) / max * 100}%` }} /></div>
      <Text size="sm">{row.value == null ? t("diagnostics.unavailable") : row.value.toLocaleString()}</Text>
    </div>)}
    <Text size="xs" c="dimmed">{t("diagnostics.zeroScale", { max: max.toLocaleString() })}</Text>
  </div>;
}

export function MeasurementContent({ data, origin, stale = false }: { data: Measurements; origin: string; stale?: boolean }) {
  const t = useTranslate();
  const sample = data.sample;
  const rows = data.row_sample;
  useEffect(() => { restoreMirrorPosition(origin); }, [origin]);
  const href = `/console/mirrors/diagnostics?source_id=${encodeURIComponent(data.source_id)}&from=${encodeURIComponent(origin)}`;
  const value = (n: number | null | undefined) => n == null ? t("diagnostics.unavailable") : n.toLocaleString();
  return <Stack gap="lg">
    <FormSection title={t("diagnostics.measurements")} columns={1}>
      {(stale || sample?.stale) && <Text role="status">{t("diagnostics.staleSnapshot")}</Text>}
      <Comparison values={[{ label: t("diagnostics.captured_events"), value: sample?.captured_events ?? null },
        { label: t("diagnostics.committed_events"), value: sample?.committed_events ?? null }]} />
      <Text size="sm">{t("diagnostics.interval")}: <Instant value={sample?.interval_start} /> — <Instant value={sample?.interval_end} /></Text>
      <DisplayField label={t("diagnostics.pending_events")} value={value(sample?.pending_events)} />
      <DisplayField label={t("diagnostics.pending_bytes")} value={value(sample?.pending_bytes)} />
      <DisplayField label={t("diagnostics.position_lag")} value={value(sample?.position_lag)} />
      <Text size="sm" c="dimmed">{t("diagnostics.backlogHelp")}</Text>
      <DisplayField label={t("diagnostics.observedAt")} value={<Instant value={sample?.observed_at} />} />
      <DisplayField label={t("diagnostics.lastCommit")} value={<Instant value={sample?.last_target_commit_at} />} />
      <DisplayField label={t("diagnostics.freshness")} value={sample?.freshness_ms == null ? t("diagnostics.unavailable") : t("diagnostics.milliseconds", { value: sample.freshness_ms.toLocaleString() })} />
    </FormSection>
    <FormSection title={t("diagnostics.publishedRows")} columns={1}>
      {data.row_sample_stale && <Text role="status">{t("diagnostics.staleRows")}</Text>}
      <Comparison values={[{ label: t("mirrors.rowEstimate"), value: data.estimated_rows },
        { label: t("diagnostics.sampledRows"), value: rows?.row_count ?? null }]} />
      <Text size="sm">{rows && data.estimated_rows != null ? t("diagnostics.rowDifference", { value: (rows.row_count - data.estimated_rows).toLocaleString() }) : t(data.published_generation_id ? "diagnostics.awaitingRows" : "diagnostics.unpublished")}</Text>
      <DisplayField label={t("mirrors.generation")} value={rows?.generation_id ?? data.published_generation_id} />
      <DisplayField label={t("diagnostics.observedAt")} value={<Instant value={rows?.observed_at} />} />
    </FormSection>
    <FormSection title={t("diagnostics.sourceChecks")}>
      <DisplayField label={t("diagnostics.runtime")} value={data.runtime_instance_id} />
      <DisplayField label={t("diagnostics.lastCheck")} value={<Instant value={data.last_source_check_at} />} />
      <DisplayField label={t("diagnostics.wait")} value={data.end_of_cycle_wait_seconds == null ? t("diagnostics.unavailable") : t("diagnostics.seconds", { value: data.end_of_cycle_wait_seconds })} />
      <Button component={ConsoleLink} href={href} variant="light" size="sm" data-mirror-return="diagnostics"
        onClick={event => rememberMirrorPosition(origin, event.currentTarget)}>{t("diagnostics.openSource")}</Button>
    </FormSection>
  </Stack>;
}

export function MirrorMeasurements({ id, origin }: { id: string; origin: string }) {
  const t = useTranslate();
  const read = useDiagnosticRead(id, signal => getMirrorMeasurements(id, signal));
  return <Stack gap="sm">
    <Group><Button size="xs" variant="subtle" onClick={() => void read.refresh()}>{t("diagnostics.refresh")}</Button></Group>
    {read.value ? <MeasurementContent data={read.value} origin={origin} stale={read.stale} /> :
      <Text role="status">{t(`diagnostics.read.${read.status}`)}</Text>}
  </Stack>;
}
