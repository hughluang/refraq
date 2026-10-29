"use client";

import {
  Button,
  Group,
  NativeSelect,
  Stack,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useState } from "react";

import { EmptyState } from "@/components/feedback/EmptyState";
import {
  getEntityChangeLogEntry,
  listEntityChangeLog,
} from "@/features/entities/api";
import type {
  ChangeLogEntryDetail,
  ChangeLogEntrySummary,
  ChangeLogPage,
} from "@/features/entities/types";
import { useEntryZone } from "@/hooks/useFormatInstant";
import { problemMessage } from "@/lib/problem";
import { wallToInstant } from "@/lib/wall-time";

type Props = {
  entityId: string;
  active: boolean;
  formatInstant: (value: string | null | undefined) => string;
};

type Filters = {
  operation: string;
  source: string;
  subject: string;
  rowIdentity: string;
  occurredFrom: string;
  occurredTo: string;
};

const EMPTY_FILTERS: Filters = {
  operation: "",
  source: "",
  subject: "",
  rowIdentity: "",
  occurredFrom: "",
  occurredTo: "",
};

export function EntityChangeLogTab({ entityId, active, formatInstant }: Props) {
  const t = useTranslate();
  const zone = useEntryZone();
  const [filters, setFilters] = useState<Filters>(EMPTY_FILTERS);
  const [beforeSequence, setBeforeSequence] = useState<number | null>(null);
  const [page, setPage] = useState<ChangeLogPage | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [detail, setDetail] = useState<ChangeLogEntryDetail | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    setBusy(true);
    setMessage(null);
    listEntityChangeLog(entityId, {
      before_sequence: beforeSequence ?? undefined,
      operation: filters.operation || undefined,
      source: filters.source || undefined,
      subject: filters.subject || undefined,
      row_identity: filters.rowIdentity || undefined,
      occurred_from: wallToInstant(filters.occurredFrom, zone) ?? undefined,
      occurred_to: wallToInstant(filters.occurredTo, zone) ?? undefined,
      signal: controller.signal,
    })
      .then((next) => {
        setPage(next);
      })
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setPage(null);
        setMessage(problemMessage(t, err, t("entities.changeLog.failed")));
      })
      .finally(() => {
        if (!controller.signal.aborted) setBusy(false);
      });
    return () => controller.abort();
  }, [active, beforeSequence, entityId, filters, t, zone]);

  useEffect(() => {
    if (!active || selected == null) return;
    const controller = new AbortController();
    getEntityChangeLogEntry(entityId, selected, { signal: controller.signal })
      .then((next) => setDetail(next))
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setDetail(null);
        setMessage(problemMessage(t, err, t("entities.changeLog.failed")));
      });
    return () => controller.abort();
  }, [active, entityId, selected, t]);

  const setFilter = (patch: Partial<Filters>) => {
    setFilters((current) => ({ ...current, ...patch }));
    setBeforeSequence(null);
    setSelected(null);
    setDetail(null);
  };

  const items = page?.items ?? [];

  return (
    <Stack>
      <Group align="end">
        <NativeSelect
          label={t("entities.changeLog.filter.operation")}
          value={filters.operation}
          onChange={(event) => setFilter({ operation: event.currentTarget.value })}
          data={[
            { value: "", label: t("entities.changeLog.filter.any") },
            { value: "insert", label: t("entities.changeLog.operation.insert") },
            { value: "update", label: t("entities.changeLog.operation.update") },
            { value: "delete", label: t("entities.changeLog.operation.delete") },
          ]}
        />
        <NativeSelect
          label={t("entities.changeLog.filter.source")}
          value={filters.source}
          onChange={(event) => setFilter({ source: event.currentTarget.value })}
          data={[
            { value: "", label: t("entities.changeLog.filter.any") },
            { value: "user", label: t("entities.changeLog.source.user") },
            {
              value: "channel_run",
              label: t("entities.changeLog.source.channelRun"),
            },
            {
              value: "unattributed",
              label: t("entities.changeLog.source.unattributed"),
            },
          ]}
        />
        <TextInput
          label={t("entities.changeLog.filter.subject")}
          description={t("entities.changeLog.filter.subjectHint")}
          value={filters.subject}
          onChange={(event) => setFilter({ subject: event.currentTarget.value })}
        />
        <TextInput
          label={t("entities.changeLog.filter.rowIdentity")}
          value={filters.rowIdentity}
          onChange={(event) =>
            setFilter({ rowIdentity: event.currentTarget.value })
          }
        />
        <TextInput
          type="datetime-local"
          step={1}
          label={t("entities.changeLog.filter.from")}
          description={t("entities.changeLog.filter.instantHint", { zone })}
          value={filters.occurredFrom}
          onChange={(event) =>
            setFilter({ occurredFrom: event.currentTarget.value })
          }
        />
        <TextInput
          type="datetime-local"
          step={1}
          label={t("entities.changeLog.filter.to")}
          description={t("entities.changeLog.filter.instantHint", { zone })}
          value={filters.occurredTo}
          onChange={(event) => setFilter({ occurredTo: event.currentTarget.value })}
        />
      </Group>
      {message ? <Text>{message}</Text> : null}
      {busy && items.length === 0 ? (
        <Text>{t("entities.changeLog.loading")}</Text>
      ) : null}
      {!busy && items.length === 0 && !message ? (
        <EmptyState message={t("entities.changeLog.empty")} />
      ) : null}
      {items.length > 0 ? (
        <Table>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t("entities.changeLog.sequence")}</Table.Th>
              <Table.Th>{t("entities.changeLog.occurredAt")}</Table.Th>
              <Table.Th>{t("entities.changeLog.operation")}</Table.Th>
              <Table.Th>{t("entities.changeLog.rowIdentity")}</Table.Th>
              <Table.Th>{t("entities.changeLog.physicalTable")}</Table.Th>
              <Table.Th>{t("entities.changeLog.source")}</Table.Th>
              <Table.Th>{t("entities.changeLog.subject")}</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {items.map((item) => (
              <Table.Tr key={item.sequence}>
                <Table.Td>
                  <Button
                    variant="subtle"
                    size="compact-sm"
                    onClick={() => setSelected(item.sequence)}
                  >
                    {item.sequence}
                  </Button>
                </Table.Td>
                <Table.Td>{formatInstant(item.occurred_at)}</Table.Td>
                <Table.Td>{operationLabel(t, item.operation)}</Table.Td>
                <Table.Td>{rowIdentity(item)}</Table.Td>
                <Table.Td>{item.physical_table}</Table.Td>
                <Table.Td>{sourceLabel(t, item.source)}</Table.Td>
                <Table.Td>
                  <SubjectCell item={item} />
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      ) : null}
      {page?.next_before_sequence != null || beforeSequence != null ? (
        <Group>
          {beforeSequence != null ? (
            <Button
              variant="default"
              size="sm"
              onClick={() => setBeforeSequence(null)}
            >
              {t("entities.changeLog.newest")}
            </Button>
          ) : null}
          {page?.next_before_sequence != null ? (
            <Button
              variant="default"
              size="sm"
              onClick={() => setBeforeSequence(page.next_before_sequence)}
            >
              {t("entities.changeLog.older")}
            </Button>
          ) : null}
        </Group>
      ) : null}
      {detail ? <ChangeLogImages detail={detail} /> : null}
    </Stack>
  );
}

function ChangeLogImages({ detail }: { detail: ChangeLogEntryDetail }) {
  const t = useTranslate();
  return (
    <Stack>
      {detail.before ? (
        <Stack gap={4} role="region" aria-label={t("entities.changeLog.before")}>
          <Text fw={600}>{t("entities.changeLog.before")}</Text>
          <ImageLines image={detail.before} />
        </Stack>
      ) : null}
      {detail.after ? (
        <Stack gap={4} role="region" aria-label={t("entities.changeLog.after")}>
          <Text fw={600}>{t("entities.changeLog.after")}</Text>
          <ImageLines image={detail.after} />
        </Stack>
      ) : null}
    </Stack>
  );
}

function ImageLines({ image }: { image: Record<string, unknown> }) {
  return (
    <Stack gap={2}>
      {Object.entries(image).map(([name, value]) => (
        <Text key={name}>
          {name}: {imageCell(value)}
        </Text>
      ))}
    </Stack>
  );
}

function imageCell(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

function SubjectCell({ item }: { item: ChangeLogEntrySummary }) {
  const label = item.subject_label ?? "";
  const id = item.subject;
  const showId = id != null && id !== label;
  if (!label && !showId) return null;
  return (
    <Stack gap={0}>
      {label ? <Text size="sm">{label}</Text> : null}
      {showId ? (
        <Text size="xs" c="dimmed" ff="monospace">
          {id}
        </Text>
      ) : null}
    </Stack>
  );
}

function rowIdentity(item: ChangeLogEntrySummary): string {
  const key = item.business_key == null ? "" : String(item.business_key);
  if (item.row_id == null) return key;
  if (!key) return String(item.row_id);
  return `${item.row_id} · ${key}`;
}

function operationLabel(
  t: (key: string) => string,
  operation: ChangeLogEntrySummary["operation"],
): string {
  if (operation === "insert") return t("entities.changeLog.operation.insert");
  if (operation === "update") return t("entities.changeLog.operation.update");
  return t("entities.changeLog.operation.delete");
}

function sourceLabel(
  t: (key: string) => string,
  source: ChangeLogEntrySummary["source"],
): string {
  if (source === "user") return t("entities.changeLog.source.user");
  if (source === "channel_run") return t("entities.changeLog.source.channelRun");
  return t("entities.changeLog.source.unattributed");
}
