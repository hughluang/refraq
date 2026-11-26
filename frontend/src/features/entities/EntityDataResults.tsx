"use client";

import {
  ActionIcon, Button, Checkbox, Drawer, Group, Loader, NativeSelect,
  Popover, Stack, Table, Text, TextInput, Tooltip, UnstyledButton,
} from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";

import { ListTable, type ListTableList } from "@/components/display/ListTable";
import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { AdjustmentsIcon, CopyIcon, SearchIcon, SortAscIcon, SortDescIcon, SortIcon } from "@/components/icons";
import { getDataRow } from "@/features/entities/accessApi";
import {
  dataAccessExpired, isMaskedPresentation, withheldNames, type DataSchemaBody,
} from "@/features/entities/accessLogic";
import type { DataAttribute, DataSchema, DataSort } from "@/features/entities/accessTypes";
import { attributeDisplayLabel, attributeTitle } from "@/features/entities/entityPresentation";
import { stringifyEntityDataJson } from "@/features/entities/entityDataJson";
import { copyText } from "@/lib/copy-text";
import { presentConsoleNotification } from "@/providers/notification-provider";

import styles from "./EntityDataResults.module.css";

type Row = Record<string, unknown>;
type RowId = number | bigint;
type Translate = (key: string, values?: Record<string, unknown>) => string;
const ROW_ID: DataAttribute = { name: "row_id", type: "integer" };

function cellValue(row: Row, attribute: DataAttribute, withheld: string[], t: Translate, expanded = false) {
  const value = row[attribute.name];
  if (withheld.includes(attribute.name)) return { text: t("entities.access.cell.withheld"), muted: true };
  if (value === null || value === undefined) return { text: "NULL", muted: true };
  if (attribute.type === "json") return { text: stringifyEntityDataJson(value, expanded ? 2 : undefined), muted: false };
  if (value === "") return { text: t("entities.data.grid.emptyString"), muted: true };
  if (attribute.type === "reference" && attribute.target == null) {
    return { text: t("entities.access.cell.inaccessibleRecord"), muted: true };
  }
  return { text: String(value), muted: false };
}

type ColumnProps = {
  schema: DataSchema | null;
  visibleFields: string[] | null;
  onChange: (fields: string[] | null) => void;
};

export function EntityDataColumns({ schema, visibleFields, onChange }: ColumnProps) {
  const t = useTranslate();
  const [open, setOpen] = useState(false);
  const [search, setSearch] = useState("");
  const attributes = schema?.attributes ?? [];
  const selected = new Set(visibleFields ?? attributes.map((attribute) => attribute.name));
  const needle = search.trim().toLowerCase();
  const matches = attributes.filter(
    ({ name, display_name }) =>
      name.toLowerCase().includes(needle) ||
      (display_name?.toLowerCase().includes(needle) ?? false),
  );

  function toggle(name: string) {
    if (selected.has(name)) selected.delete(name);
    else selected.add(name);
    const next = attributes.map((attribute) => attribute.name).filter((field) => selected.has(field));
    onChange(next.length === attributes.length ? null : next);
  }

  return (
    <Popover opened={open} onDismiss={() => setOpen(false)} position="bottom-end" width="min(20rem, calc(100vw - 2rem))" trapFocus withRoles>
      <Popover.Target>
        <Button type="button" size="sm" variant="default" leftSection={<AdjustmentsIcon />} disabled={!attributes.length}
          aria-expanded={open} onClick={() => { setSearch(""); setOpen(!open); }}>
          {t("entities.data.grid.columns")}
        </Button>
      </Popover.Target>
      <Popover.Dropdown>
        <Stack gap="sm">
          <TextInput aria-label={t("entities.data.grid.findColumn")} placeholder={t("entities.data.grid.findColumn")}
            leftSection={<SearchIcon />} value={search} onChange={(e) => setSearch(e.currentTarget.value)} data-autofocus />
          <Stack gap="xs" mah="min(19rem, 45dvh)" style={{ overflowY: "auto" }} py={2}>
            {matches.map((attribute) => (
              <Checkbox key={attribute.name} label={attributeDisplayLabel(attribute)} checked={selected.has(attribute.name)} onChange={() => toggle(attribute.name)} />
            ))}
            {!matches.length && <Text size="sm" c="dimmed">{t("entities.data.grid.noColumns")}</Text>}
          </Stack>
          {visibleFields !== null && (
            <Button type="button" size="compact-sm" variant="subtle" onClick={() => onChange(null)}>{t("entities.data.grid.showAll")}</Button>
          )}
        </Stack>
      </Popover.Dropdown>
    </Popover>
  );
}

function columnState(attribute: DataAttribute, t: Translate): string {
  const labels: string[] = [];
  if (isMaskedPresentation(attribute.presentation?.levels)) labels.push(t("entities.access.cell.masked"));
  if (attribute.presentation?.row_varying) labels.push(t("entities.access.cell.rowVarying"));
  if (attribute.writable === false) labels.push(t("entities.data.readOnly"));
  return labels.join(" · ");
}

type DetailProps = {
  rowId: RowId;
  schema: DataSchema;
  tableName: string;
  narrow: DataSchemaBody;
  onClose: () => void;
  onDetailError: (error: unknown) => void;
};

function RecordDrawer({ rowId, schema, tableName, narrow, onClose, onDetailError }: DetailProps) {
  const t = useTranslate();
  const [row, setRow] = useState<Row | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const callbacks = useRef({ onDetailError, onClose, t });
  callbacks.current = { onDetailError, onClose, t };
  const narrowType = narrow.narrow?.type;
  const narrowId = narrow.narrow?.id;
  useEffect(() => {
    let current = true;
    setRow(null);
    setFailed(false);
    const scope = narrowType ? { narrow: { type: narrowType, ...(narrowId ? { id: narrowId } : {}) } } : {};
    void getDataRow(tableName, { row_id: rowId, ...scope }).then(({ row: result }) => {
      if (current) setRow(result);
    }).catch((err: unknown) => {
      if (!current) return;
      if (dataAccessExpired(err)) {
        callbacks.current.onClose();
        callbacks.current.onDetailError(err);
        return;
      }
      setFailed(true);
      presentProblemNotification(callbacks.current.t, err);
    });
    return () => { current = false; };
  }, [rowId, tableName, narrowType, narrowId, attempt]);

  const withheld = row ? withheldNames(row, schema.withheld_field) : [];
  const columns = [ROW_ID, ...schema.attributes];
  async function copy(text: string) {
    try {
      await copyText(text);
      presentConsoleNotification({ type: "success", title: t("common.copy.success") });
    } catch {
      presentConsoleNotification({ type: "error", title: t("common.copy.failed") });
    }
  }
  return (
    <Drawer opened onClose={onClose} position="right" size="min(32rem, 100vw)"
      title={t("entities.data.grid.record", { id: String(rowId) })} closeButtonProps={{ "aria-label": t("form.dialog.close") }}>
      {failed ? <Button type="button" variant="default" onClick={() => setAttempt((n) => n + 1)}>{t("common.retry")}</Button>
        : !row ? <Loader size="sm" role="status" aria-label={t("entities.data.grid.loadingRecord")} />
        : <dl className={styles.details}>
          {columns.filter((attribute) => Object.hasOwn(row, attribute.name)).map((attribute) => {
            const value = cellValue(row, attribute, withheld, t, true);
            const state = columnState(attribute, t);
            const title = attributeTitle(attribute);
            const hasDisplayName = Boolean(attribute.display_name?.trim());
            return (
              <div key={attribute.name} className={styles.detailField}>
                <dt>
                  <Text span size="sm" fw={600}>{title}</Text>
                  {hasDisplayName && <Text span size="xs" c="dimmed" ff="monospace">{attribute.name}</Text>}
                  {state && <Text span size="xs" c="dimmed">{state}</Text>}
                  {!value.muted && (
                    <Tooltip label={t("entities.data.grid.copyValue", { field: title })}>
                      <ActionIcon type="button" variant="subtle" size="sm" color="gray"
                        aria-label={t("entities.data.grid.copyValue", { field: title })} onClick={() => void copy(value.text)}>
                        <CopyIcon />
                      </ActionIcon>
                    </Tooltip>
                  )}
                </dt>
                <dd data-json={attribute.type === "json" || undefined} data-muted={value.muted || undefined}>{value.text}</dd>
              </div>
            );
          })}
        </dl>}
    </Drawer>
  );
}

type ResultsProps = {
  schema: DataSchema | null;
  rows: Row[];
  list: ListTableList;
  tableName: string;
  narrow: DataSchemaBody;
  visibleFields: string[] | null;
  sort: DataSort | null;
  onSort: (sort: DataSort | null) => void;
  onPageSize: (size: number) => void;
  onDetailError: (error: unknown) => void;
  noMatchMessage?: string;
  noMatchAction?: ReactNode;
};

export function EntityDataResults({
  schema, rows, list, tableName, narrow, visibleFields, sort, onSort, onPageSize,
  onDetailError, noMatchMessage, noMatchAction,
}: ResultsProps) {
  const t = useTranslate();
  const [detailId, setDetailId] = useState<RowId | null>(null);
  const opener = useRef<HTMLButtonElement | null>(null);
  const pageSizeId = useId();
  const selected = visibleFields && new Set(visibleFields);
  const fields = (schema?.attributes ?? []).filter(({ name }) => !selected || selected.has(name));
  const primary = fields.find((attr) => attr.name === schema?.business_key) ?? ROW_ID;
  const columns = [primary, ...fields.filter((attr) => attr.name !== primary.name)];
  const currentSort = sort ?? { field: "row_id", direction: "asc" };
  const limit = schema?.limits?.page_limit_max ?? 50;
  const sizes = [...new Set([25, 50, 100, 200, list.pageSize])].filter((n) => n <= limit).sort((a, b) => a - b);
  const scopeKey = JSON.stringify([tableName, narrow.narrow?.type, narrow.narrow?.id, schema?.access?.policy_revision]);

  function closeDetails() {
    setDetailId(null);
    window.requestAnimationFrame(() => {
      if (opener.current?.isConnected) opener.current.focus({ preventScroll: true });
    });
  }

  return (
    <div className={styles.frame}>
      <ListTable list={list} columnCount={columns.length} minWidth={Math.max(200, columns.length * 155)}
        emptyMessage={t("entities.data.empty")} noMatchMessage={noMatchMessage} noMatchAction={noMatchAction}
        pageSizeControl={schema && (
          <Group gap={6}>
            <Text component="label" htmlFor={pageSizeId} size="xs" c="dimmed">
              {t("entities.data.grid.pageSize")}
            </Text>
            <NativeSelect id={pageSizeId} size="xs" w={66} value={String(list.pageSize)}
              data={sizes.map(String)} onChange={(e) => onPageSize(Number(e.currentTarget.value))} />
          </Group>
        )}
        head={<Table.Tr>{columns.map((attribute) => {
          const sortable = attribute.type !== "json" && schema != null;
          const direction = currentSort.field === attribute.name ? currentSort.direction : null;
          const nextSort = direction === "asc" ? { field: attribute.name, direction: "desc" as const } :
            direction === "desc" ? null : { field: attribute.name, direction: "asc" as const };
          const SortIndicator = direction === "asc" ? SortAscIcon : direction === "desc" ? SortDescIcon : SortIcon;
          const state = columnState(attribute, t);
          const title = attributeTitle(attribute);
          const hasDisplayName = Boolean(attribute.display_name?.trim());
          return (
            <Table.Th key={attribute.name} scope="col" aria-sort={direction ? (direction === "asc" ? "ascending" : "descending") : undefined}>
              {sortable ? (
                <UnstyledButton type="button" className={styles.heading} onClick={() => onSort(nextSort)}
                  title={t(nextSort ? (nextSort.direction === "asc" ? "entities.data.grid.sortAsc" : "entities.data.grid.sortDesc") : "entities.data.grid.clearSort", { field: title })}>
                  <span>{title}</span><SortIndicator size={14} aria-hidden />
                </UnstyledButton>
              ) : <span className={styles.fieldName}>{title}</span>}
              {hasDisplayName && <Text component="div" size="xs" c="dimmed" ff="monospace" truncate fw={400}>{attribute.name}</Text>}
              {state && <Text component="div" size="xs" c="dimmed" truncate title={state} fw={400}>{state}</Text>}
            </Table.Th>
          );
        })}</Table.Tr>}
      >
        {rows.map((row) => {
          const rowId = row.row_id as RowId;
          const withheld = withheldNames(row, schema?.withheld_field ?? null);
          return (
            <Table.Tr key={String(rowId)}>
              {columns.map((attribute, index) => {
                const value = cellValue(row, attribute, withheld, t);
                return <Table.Td key={attribute.name}>
                  {index === 0 ? (
                    <UnstyledButton type="button" className={styles.recordLink}
                      title={t("entities.data.grid.openRecord", { id: String(rowId) })} onClick={(event) => {
                        opener.current = event.currentTarget;
                        setDetailId(rowId);
                      }}>
                      {value.text}
                    </UnstyledButton>
                  ) : <span className={styles.cell} data-muted={value.muted || undefined}
                    data-number={["integer", "number", "decimal"].includes(attribute.type) || undefined}>{value.text}</span>}
                </Table.Td>;
              })}
            </Table.Tr>
          );
        })}
      </ListTable>
      {schema && detailId != null && (
        <RecordDrawer key={scopeKey + String(detailId)} rowId={detailId} schema={schema} tableName={tableName} narrow={narrow}
          onClose={closeDetails} onDetailError={onDetailError} />
      )}
    </div>
  );
}
