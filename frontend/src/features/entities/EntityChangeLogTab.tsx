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
import {
  useChangeLogDraft,
  type ChangeLogFilters,
} from "@/features/entities/changeLogDraft";
import type {
  ChangeLogEntrySummary,
  ChangeLogPage,
  ChangeLogSide,
} from "@/features/entities/types";
import { useEntryZone } from "@/hooks/useFormatInstant";
import { problemMessage } from "@/lib/problem";
import { wallToInstant } from "@/lib/wall-time";

type Props = {
  entityId: string;
  active: boolean;
  formatInstant: (value: string | null | undefined) => string;
};

export function EntityChangeLogTab({ entityId, active, formatInstant }: Props) {
  const t = useTranslate();
  const zone = useEntryZone();
  const { filters, setFilters } = useChangeLogDraft();
  const [cursor, setCursor] = useState<string | null>(null);
  const [page, setPage] = useState<ChangeLogPage | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [detail, setDetail] = useState<ChangeLogEntrySummary | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [boundEntityId, setBoundEntityId] = useState(entityId);
  // The continuation and the open entry belong to one entity. Adjust them
  // while rendering so this pass's list effect cannot send the previous cursor.
  if (entityId !== boundEntityId) {
    setBoundEntityId(entityId);
    setCursor(null);
    setPage(null);
    setSelected(null);
    setDetail(null);
  }

  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    setBusy(true);
    setMessage(null);
    listEntityChangeLog(entityId, {
      cursor: cursor ?? undefined,
      operation: filters.operation || undefined,
      source: filters.source || undefined,
      subject: filters.subject || undefined,
      row_identity: filters.rowIdentity || undefined,
      version_id: filters.versionId || undefined,
      row_id: filters.rowId || undefined,
      occurred_from: wallToInstant(filters.occurredFrom, zone) ?? undefined,
      occurred_to: wallToInstant(filters.occurredTo, zone) ?? undefined,
      signal: controller.signal,
    })
      .then((next) => {
        if (controller.signal.aborted) return;
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
  }, [active, cursor, entityId, filters, t, zone]);

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

  const setFilter = (patch: Partial<ChangeLogFilters>) => {
    setFilters((current) => ({ ...current, ...patch }));
    setCursor(null);
    setSelected(null);
    setDetail(null);
  };

  const items = page?.items ?? [];
  const nextCursor = page?.next_cursor ?? null;

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
          label={t("entities.changeLog.filter.versionId")}
          value={filters.versionId}
          onChange={(event) =>
            setFilter({ versionId: event.currentTarget.value })
          }
        />
        <TextInput
          label={t("entities.changeLog.filter.rowId")}
          value={filters.rowId}
          onChange={(event) => setFilter({ rowId: event.currentTarget.value })}
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
      {!busy && items.length === 0 && !message && cursor == null && nextCursor == null ? (
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
              <Table.Th>{t("entities.changeLog.version")}</Table.Th>
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
                <Table.Td>
                  <Stack gap={0}>
                    <Text size="sm">{item.version_number}</Text>
                    <Text size="xs" c="dimmed" ff="monospace">
                      {item.version_id}
                    </Text>
                  </Stack>
                </Table.Td>
                <Table.Td>{sourceLabel(t, item.source)}</Table.Td>
                <Table.Td>
                  <SubjectCell item={item} />
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      ) : null}
      {nextCursor != null || cursor != null ? (
        <Group>
          {cursor != null ? (
            <Button variant="default" size="sm" onClick={() => setCursor(null)}>
              {t("entities.changeLog.newest")}
            </Button>
          ) : null}
          {nextCursor != null ? (
            <Button
              variant="default"
              size="sm"
              onClick={() => setCursor(nextCursor)}
            >
              {t("entities.changeLog.older")}
            </Button>
          ) : null}
        </Group>
      ) : null}
      {detail ? (
        <Stack>
          <SideBlock name="before" side={detail.before} />
          <SideBlock name="after" side={detail.after} />
        </Stack>
      ) : null}
    </Stack>
  );
}

function SideBlock({
  name,
  side,
}: {
  name: "before" | "after";
  side: ChangeLogSide;
}) {
  const t = useTranslate();
  const label = t(
    name === "before" ? "entities.changeLog.before" : "entities.changeLog.after",
  );
  if (side.state === "absent") return null;
  return (
    <Stack gap={4} role="region" aria-label={label}>
      <Text fw={600}>{label}</Text>
      {side.state === "unavailable" ? (
        <Text>{t("entities.changeLog.unavailable")}</Text>
      ) : (
        <ImageLines image={side.values ?? {}} />
      )}
    </Stack>
  );
}

function ImageLines({ image }: { image: Record<string, unknown> }) {
  const t = useTranslate();
  const withheld = new Set(
    Array.isArray(image.__withheld) ? image.__withheld.map(String) : [],
  );
  return (
    <Stack gap={2}>
      {Object.entries(image)
        .filter(([name]) => name !== "__withheld")
        .map(([name, value]) => (
          <Text key={name}>
            {name}:{" "}
            {withheld.has(name)
              ? t("entities.changeLog.withheld")
              : imageCell(value)}
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
  const ids: string[] = [];
  for (const side of [item.before, item.after]) {
    if (side.state !== "visible" || side.values == null) continue;
    const rowId = side.values.row_id;
    if (rowId == null) continue;
    const text = String(rowId);
    if (!ids.includes(text)) ids.push(text);
  }
  return ids.join(" · ");
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
