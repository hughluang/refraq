"use client";

import { Button, Code, Group, Stack, Text } from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import { useEffect, useRef, useState } from "react";
import { sourceRecordAdapter } from "@/components/form/recordPickerAdapters";
import { RecordPicker } from "@/components/form/RecordPicker";
import { TextField } from "@/components/form/TextField";
import { PageChrome } from "@/components/layout/PageChrome";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { useConsoleLocation, useConsoleNavigation } from "@/components/navigation/useConsoleNavigation";
import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { getSource } from "@/features/sources/api/sources";
import { copyText } from "@/lib/copy-text";
import { ApiError } from "@/lib/api";
import { getMirrorSetup, listMirrorInventory } from "../api";
import { OperationsNavigation, operationsHref } from "../OperationsNavigation";
import {
  acceptSiteValue, acceptedSite, agentInstruction, instructionVariables, runtimeConfig,
  stepCommand, type SetupGuide, type SetupSelection,
} from "./setupModel";
import { setupHref, type SetupStep } from "./setupLinks";

type LoadStatus = "loading" | "ready" | "forbidden" | "unloaded";
type LoadedSource = {
  engine: string | null;
  name: string;
  access: Record<string, unknown> | null;
  tables: string[];
  truncated: boolean;
};

export function MirrorSetup() {
  const t = useTranslate();
  const translate = useRef(t);
  translate.current = t;
  const { open } = useNotification();
  const { search } = useConsoleLocation();
  const { push } = useConsoleNavigation();
  const sourceId = search.get("source_id") ?? "";
  const step = search.get("step") ?? "";
  const [guide, setGuide] = useState<SetupGuide | null>(null);
  const [status, setStatus] = useState<LoadStatus>("loading");
  const [attempt, setAttempt] = useState(0);
  const [source, setSource] = useState<LoadedSource | null>(null);
  const [sourceStatus, setSourceStatus] = useState<LoadStatus>("ready");
  const [sourceAttempt, setSourceAttempt] = useState(0);
  const [values, setValues] = useState<Record<string, string>>({});

  useEffect(() => {
    const controller = new AbortController();
    setStatus("loading");
    void getMirrorSetup(controller.signal).then(value => {
      if (!controller.signal.aborted) {
        setGuide(value);
        setStatus("ready");
      }
    }).catch(error => {
      if (controller.signal.aborted) return;
      if (error instanceof ApiError && (error.status === 401 || error.status === 403)) setStatus("forbidden");
      else {
        setStatus("unloaded");
        presentProblemNotification(translate.current, error, { onRetry: () => setAttempt(value => value + 1) });
      }
    });
    return () => controller.abort();
  }, [attempt]);

  useEffect(() => {
    if (!sourceId) {
      setSource(null);
      setSourceStatus("ready");
      return;
    }
    const controller = new AbortController();
    setSource(null);
    setSourceStatus("loading");
    void Promise.all([
      getSource(sourceId, { signal: controller.signal }),
      listMirrorInventory({ source_id: sourceId, limit: 100, offset: 0 }),
    ]).then(([record, page]) => {
      if (controller.signal.aborted) return;
      const tables = page.items.map(item => item.qualified_table);
      setSource({
        engine: record.source.engine,
        name: record.source.name,
        access: record.source.access ?? null,
        tables,
        truncated: page.total > tables.length,
      });
      setSourceStatus("ready");
    }).catch(error => {
      if (controller.signal.aborted) return;
      setSource(null);
      if (error instanceof ApiError && (error.status === 401 || error.status === 403)) setSourceStatus("forbidden");
      else {
        setSourceStatus("unloaded");
        presentProblemNotification(translate.current, error, { onRetry: () => setSourceAttempt(value => value + 1) });
      }
    });
    return () => controller.abort();
  }, [sourceId, sourceAttempt]);

  useEffect(() => {
    if (!step || status !== "ready") return;
    document.getElementById(`setup-${step}`)?.scrollIntoView?.({ block: "nearest" });
  }, [step, status]);

  const site = guide ? acceptedSite(guide, values) : {};
  const selection: SetupSelection | null = guide ? {
    guide,
    engine: source?.engine ?? null,
    access: source?.access ?? null,
    tables: source?.tables ?? [],
    tablesTruncated: source?.truncated ?? false,
    sourceId,
    sourceName: source?.name ?? "",
    site,
  } : null;
  const built = selection ? instructionVariables(t, selection) : null;
  const instruction = selection ? agentInstruction(t, selection) : "";
  const configuration = selection ? JSON.stringify(runtimeConfig(selection), null, 2) : "";

  function selectSource(id: string | null) {
    push(setupHref(id, search.get("step")));
  }

  async function copy(text: string) {
    try {
      await copyText(text);
      open?.({ type: "success", message: t("common.copy.success") });
    } catch {
      open?.({ type: "error", message: t("common.copy.failed") });
    }
  }

  return <PageChrome title={t("mirrorSetup.title")} description={t("mirrorSetup.description")}
    status={status} forbiddenReason="mirror:read" onRetry={() => setAttempt(value => value + 1)}
    tabs={<OperationsNavigation view="setup" scope={sourceId ? { source_id: sourceId } : {}} />}>
    {guide && selection && built && <Stack gap="xl">
      <RecordPicker editable clearable label={t("mirrorSetup.source")} placeholder={t("mirrorSetup.noSource")}
        adapter={sourceRecordAdapter()} value={sourceId || null} onChange={id => selectSource(id)} />
      {sourceId && sourceStatus === "loading" && <Text size="sm">{t("common.loading")}</Text>}
      {sourceStatus === "forbidden" && <Text size="sm" role="status">{t("mirrorSetup.sourceForbidden")}</Text>}
      {sourceStatus === "unloaded" && <Button variant="subtle" size="xs" w="fit-content" onClick={() => setSourceAttempt(value => value + 1)}>{t("common.retry")}</Button>}
      {source && <Text size="sm">{t("mirrorSetup.prompt.endpoint", built.vars)} {t("mirrorSetup.prompt.tables", built.vars)}</Text>}
      <Stack gap="sm">
        <Text fw={500}>{t("mirrorSetup.inputs.title")}</Text>
        <Text size="sm" c="dimmed">{t("mirrorSetup.inputs.help")}</Text>
        {guide.site_inputs.map(input => {
          const raw = values[input.token] ?? "";
          const invalid = raw.trim() !== "" && !acceptSiteValue(input.kind, raw, guide.patterns);
          return <TextField key={input.token} editable label={t(`mirrorSetup.input.${input.token}`)} value={raw}
            error={invalid ? t(input.kind === "https_origin" ? "mirrorSetup.inputs.invalidOrigin" : "mirrorSetup.inputs.invalid") : undefined}
            onChange={event => setValues(current => ({ ...current, [input.token]: event.currentTarget.value }))} />;
        })}
      </Stack>
      <Copyable label={t("mirrorSetup.prompt.title")} help={t("mirrorSetup.prompt.help")} text={instruction}
        copyLabel={t("mirrorSetup.prompt.copy")} onCopy={() => void copy(instruction)} />
      <Copyable label={t("mirrorSetup.config.title")} help={t("mirrorSetup.config.help")} text={configuration}
        copyLabel={t("mirrorSetup.config.copy")} onCopy={() => void copy(configuration)} />
      <Stack gap="sm">
        {guide.steps.map(id => {
          const command = stepCommand(id as SetupStep, built.commands, built.setting);
          const engine = guide.engines.find(item => item.code === selection.engine);
          return <details key={id} id={`setup-${id}`} open={step === id}>
            <summary>{t(`mirrorSetup.step.${id}.title`)}</summary>
            <Stack gap="sm" pt="sm">
              <Text size="sm" c="dimmed">{t(`mirrorSetup.step.${id}.owner`)}</Text>
              <Text size="sm">{t(`mirrorSetup.step.${id}.body`, built.vars)}</Text>
              {id === "source" && engine && <Stack component="ul" gap={4}>
                {[...engine.prerequisites, engine.snapshot_prerequisite].map(name => <Text component="li" size="sm" key={name}>{t(`mirrorSetup.prerequisite.${engine.code}.${name}`)}</Text>)}
              </Stack>}
              {id === "runtime" && <Stack component="ul" gap={4}>
                {guide.runtime.fault_codes.map(code => <Text component="li" size="sm" key={code}><Text component="span" ff="monospace" size="sm">{code}</Text> {t(`mirrorSetup.fault.${code}`)}</Text>)}
              </Stack>}
              {id === "config" && guide.deployment_owned.map(key => <Text size="sm" key={key}>{t(`mirrorSetup.owned.${key}`)}</Text>)}
              {command && <Copyable label={t("mirrorSetup.command.label")} text={command} copyLabel={t("mirrorSetup.command.copy")} onCopy={() => void copy(command)} />}
              {id === "verify" && sourceId && <Group gap="md">
                <ConsoleLink href={`/console/sources/${encodeURIComponent(sourceId)}`}>{t("mirrorSetup.openSource")}</ConsoleLink>
                <ConsoleLink href={operationsHref("inventory", { source_id: sourceId })}>{t("mirrorSetup.openInventory")}</ConsoleLink>
              </Group>}
            </Stack>
          </details>;
        })}
      </Stack>
    </Stack>}
  </PageChrome>;
}

function Copyable({ label, help, text, copyLabel, onCopy }: {
  label: string; help?: string; text: string; copyLabel: string; onCopy: () => void;
}) {
  return <Stack gap="xs" miw={0}>
    <Group justify="space-between" wrap="wrap">
      <Text fw={500} size="sm">{label}</Text>
      <Button size="xs" variant="default" onClick={onCopy}>{copyLabel}</Button>
    </Group>
    {help && <Text size="sm" c="dimmed">{help}</Text>}
    <Code block style={{ maxWidth: "100%", overflowX: "auto", whiteSpace: "pre-wrap" }}>{text}</Code>
  </Stack>;
}
