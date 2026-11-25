"use client";

import { Button, Group, Modal, Stack, Tabs, Text } from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import { useLayoutEffect, useRef, useState } from "react";

import { StatusBadge } from "@/components/display/StatusBadge";
import { checkCapture, checkCaptureDraft } from "@/features/sources/api/sources";
import type { Tone } from "@/components/display/statusTone";
import type {
  CaptureCheckItem,
  CaptureCheckResult,
  CaptureCheckTable,
  CaptureCredential,
  Engine,
  SourceAccess,
} from "@/features/sources/types";

type Props = {
  sourceId?: string;
  engine: Engine;
  draftAccess?: SourceAccess;
  captureCredential?: CaptureCredential;
  disabled: boolean;
  validate: () => boolean;
};

type ResultTab = "items" | "tables";

const TONE: Record<CaptureCheckItem["result"], Tone> = {
  pass: "success",
  fail: "danger",
  unknown: "warning",
  not_applicable: "neutral",
};

export function SourceCapturePrecheck({
  sourceId, engine, draftAccess, captureCredential, disabled, validate,
}: Props) {
  const t = useTranslate();
  const { open } = useNotification();
  const generation = useRef(0);
  const [pending, setPending] = useState(false);
  const [failure, setFailure] = useState<"failed" | "timeout" | "unavailable" | null>(null);
  const [result, setResult] = useState<CaptureCheckResult | null>(null);
  const [tab, setTab] = useState<ResultTab>("items");
  const fingerprint = JSON.stringify({ sourceId, engine, draftAccess, captureCredential });

  useLayoutEffect(() => {
    setResult(null);
    setFailure(null);
    return () => { generation.current += 1; };
  }, [fingerprint]);

  async function check() {
    if (!validate()) return;
    const attempt = ++generation.current;
    setPending(true);
    setFailure(null);
    setResult(null);
    const body = {
      ...(draftAccess ? { engine, access: draftAccess } : {}),
      ...(captureCredential ? { capture_credential: captureCredential } : {}),
    };
    try {
      const next = sourceId
        ? await checkCapture(sourceId, body)
        : await checkCaptureDraft({ engine, access: draftAccess ?? {}, ...body });
      if (attempt !== generation.current) return;
      if (!next.ok) {
        setFailure(next.code === "SOURCE_CAPTURE_CHECK_TIMEOUT" ? "timeout" : "failed");
        open?.({ type: "error", message: t(next.code === "SOURCE_CAPTURE_CHECK_TIMEOUT" ? "sources.precheck.timeout" : "sources.precheck.failed") });
        return;
      }
      setTab("items");
      setResult(next);
    } catch {
      if (attempt !== generation.current) return;
      setFailure("unavailable");
      open?.({ type: "error", message: t("sources.precheck.unavailable") });
    } finally {
      if (attempt === generation.current) setPending(false);
    }
  }

  return (
    <Stack gap="sm">
      <Group gap="sm" align="center">
        <Button type="button" size="sm" variant="light" disabled={disabled} loading={pending} onClick={() => void check()}>
          {t("sources.precheck.check")}
        </Button>
        <span role="status" aria-live="polite">
          {failure && <StatusBadge tone="danger" labelKey={`sources.precheck.${failure}`} />}
        </span>
      </Group>
      <Modal
        opened={Boolean(result?.ok)}
        onClose={() => setResult(null)}
        title={t("sources.precheck.title")}
        size="lg"
        closeButtonProps={{ "aria-label": t("form.dialog.close") }}
      >
        {result?.ok && (
          <CheckResult result={result} tab={tab} onTab={setTab} />
        )}
      </Modal>
    </Stack>
  );
}

function CheckResult({
  result, tab, onTab,
}: {
  result: CaptureCheckResult;
  tab: ResultTab;
  onTab: (tab: ResultTab) => void;
}) {
  const t = useTranslate();
  const tables = result.tables?.items ?? [];
  const counts = {
    failing: tables.filter((table) => table.result === "fail").length,
    unknown: tables.filter((table) => table.result === "unknown").length,
    passing: tables.filter((table) => table.result === "pass").length,
  };

  return (
    <Stack gap="sm">
      <Text size="sm" c="dimmed">{t("sources.precheck.advisory")}</Text>
      {result.credential && <Text size="sm">{t(`sources.precheck.credential.${result.credential}`)}</Text>}
      {result.credential === "access" && (
        <Text size="sm">{t("sources.precheck.note.access_credential")}</Text>
      )}
      <Tabs keepMounted={false} value={tab} onChange={(next) => { if (next === "items" || next === "tables") onTab(next); }}>
        <Tabs.List>
          <Tabs.Tab value="items">{t("sources.precheck.tab.items")}</Tabs.Tab>
          <Tabs.Tab value="tables">{t("sources.precheck.tab.tables")}</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="items">
          <Stack gap="xs" pt="md">
            {(result.items ?? []).map((entry) => (
              <Group key={entry.key} gap="sm" align="flex-start" wrap="nowrap">
                <StatusBadge tone={TONE[entry.result]} labelKey={`sources.precheck.result.${entry.result}`} />
                <Stack gap={0}>
                  <Text size="sm">{t(`sources.precheck.item.${entry.key}`)}</Text>
                  {entry.observed != null && entry.observed !== "" && (
                    <Text size="xs" c="dimmed">{t("sources.precheck.observed", { value: entry.observed })}</Text>
                  )}
                  {entry.action && <Text size="xs">{t(`sources.precheck.action.${entry.action}`)}</Text>}
                </Stack>
              </Group>
            ))}
          </Stack>
        </Tabs.Panel>
        <Tabs.Panel value="tables">
          <Stack gap="xs" pt="md">
            {result.tables && <Text size="sm">{t("sources.precheck.tables.summary", counts)}</Text>}
            {result.tables?.truncated && (
              <Text size="xs" c="dimmed">
                {t("sources.precheck.tables.truncated", { shown: tables.length, total: result.tables.total })}
              </Text>
            )}
            {tables.length === 0 ? (
              <Text size="sm" c="dimmed">{t("sources.precheck.tables.none")}</Text>
            ) : (
              tables.map((table) => <TableRow key={table.name} table={table} />)
            )}
          </Stack>
        </Tabs.Panel>
      </Tabs>
    </Stack>
  );
}

function TableRow({ table }: { table: CaptureCheckTable }) {
  const t = useTranslate();
  return (
    <Group gap="sm" align="flex-start" wrap="nowrap">
      <StatusBadge tone={TONE[table.result]} labelKey={`sources.precheck.result.${table.result}`} />
      <Stack gap={0}>
        <Text size="sm">{table.name}</Text>
        {table.cause && <Text size="xs">{t(`sources.precheck.cause.${table.cause}`)}</Text>}
        {table.observed != null && table.observed !== "" && (
          <Text size="xs" c="dimmed">{t("sources.precheck.observed", { value: table.observed })}</Text>
        )}
      </Stack>
    </Group>
  );
}
