"use client";

import {
  Badge,
  Button,
  Drawer,
  Group,
  NumberInput,
  Select,
  Stack,
  Table,
  Text,
  Textarea,
} from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ListTable } from "@/components/display/ListTable";
import { FillColumn } from "@/components/layout/FillColumn";
import { SectionHeader } from "@/components/layout/SectionHeader";
import {
  deleteJoin,
  getJoinPath,
  listObjectJoins,
  searchCatalogColumns,
  upsertJoin,
} from "@/features/sources/api";
import type { CatalogObject, JoinPathResult } from "@/features/sources/types";
import { usePagedList } from "@/hooks/usePagedList";
import { ApiError } from "@/lib/api";
import { listPresentationOf } from "@/lib/list-state";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;

type SelectOption = { value: string; label: string };

type JoinsTabProps = {
  object: CatalogObject;
  writable: boolean;
};

function columnLabel(detail: CatalogObject, columnId: string): string {
  const col = detail.columns.find((c) => c.id === columnId);
  if (!col) return columnId;
  return `${col.name} · ${col.locator_key}`;
}

export function JoinsTab({ object, writable }: JoinsTabProps) {
  const t = useTranslate();
  const { open } = useNotification();
  const [saving, setSaving] = useState(false);
  const [joinFromId, setJoinFromId] = useState<string | null>(
    object.columns[0]?.id ?? null,
  );
  const [joinToId, setJoinToId] = useState<string | null>(null);
  const [joinEvidence, setJoinEvidence] = useState("");
  const [joinKind, setJoinKind] = useState<string | null>("INNER");
  const [joinExpression, setJoinExpression] = useState("");
  const [toSearch, setToSearch] = useState("");
  const [debouncedToSearch, setDebouncedToSearch] = useState("");
  const [toOptions, setToOptions] = useState<SelectOption[]>([]);
  const [toSearchLoading, setToSearchLoading] = useState(false);
  const [maxHops, setMaxHops] = useState(2);
  const [pathLoading, setPathLoading] = useState(false);
  const [pathResult, setPathResult] = useState<JoinPathResult | null>(null);
  const [pathDrawerOpen, setPathDrawerOpen] = useState(false);

  const onError = useCallback(
    (message: string) => {
      open?.({ type: "error", message });
    },
    [open],
  );
  const fetchPage = useCallback(
    (query: PageQuery) => listObjectJoins(object.id, query),
    [object.id],
  );
  const {
    items: joins,
    total,
    page,
    setPage,
    pageSize,
    reload,
    loading,
    error,
  } = usePagedList({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
    resetDeps: [object.id],
    onError,
  });
  const listPresentation = listPresentationOf({
    loading,
    error,
    total,
    itemCount: joins.length,
    filtered: false,
  });

  useEffect(() => {
    setJoinFromId(object.columns[0]?.id ?? null);
  }, [object.id, object.columns]);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedToSearch(toSearch), 300);
    return () => window.clearTimeout(timer);
  }, [toSearch]);

  useEffect(() => {
    const query = debouncedToSearch.trim();
    if (!query) {
      setToOptions((prev) =>
        joinToId ? prev.filter((o) => o.value === joinToId) : [],
      );
      return;
    }
    let cancelled = false;
    setToSearchLoading(true);
    void searchCatalogColumns({
      q: query,
      source_id: object.source_id,
      limit: 20,
    })
      .then((data) => {
        if (cancelled) return;
        const next = data.items.map((c) => ({
          value: c.id,
          label: `${c.name} · ${c.locator_key}`,
        }));
        setToOptions((prev) => {
          if (!joinToId || next.some((o) => o.value === joinToId)) return next;
          const selected = prev.find((o) => o.value === joinToId);
          return selected ? [selected, ...next] : next;
        });
      })
      .catch((err) => {
        if (cancelled) return;
        open?.({
          type: "error",
          message: err instanceof ApiError ? err.detail : String(err),
        });
      })
      .finally(() => {
        if (!cancelled) setToSearchLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [debouncedToSearch, object.source_id, joinToId, open]);

  const saveJoinEdge = async () => {
    const evidence = joinEvidence.trim();
    if (!evidence) {
      open?.({ type: "error", message: t("catalog.joins.evidenceRequired") });
      return;
    }
    if (!joinFromId || !joinToId) {
      open?.({ type: "error", message: t("catalog.joins.toColumnRequired") });
      return;
    }
    setSaving(true);
    try {
      await upsertJoin({
        from_column_id: joinFromId,
        to_column_id: joinToId,
        evidence,
        join_kind: joinKind || "INNER",
        join_expression: joinExpression.trim() || null,
      });
      await reload();
      setJoinEvidence("");
      setJoinExpression("");
      open?.({ type: "success", message: t("catalog.joins.saved") });
    } catch (err) {
      open?.({
        type: "error",
        message: err instanceof ApiError ? err.detail : String(err),
      });
    } finally {
      setSaving(false);
    }
  };

  const removeJoinEdge = async (joinId: string) => {
    setSaving(true);
    try {
      await deleteJoin(joinId);
      await reload();
      open?.({ type: "success", message: t("catalog.joins.deleted") });
    } catch (err) {
      open?.({
        type: "error",
        message: err instanceof ApiError ? err.detail : String(err),
      });
    } finally {
      setSaving(false);
    }
  };

  const explorePaths = async () => {
    setPathLoading(true);
    try {
      const data = await getJoinPath({
        start: object.id,
        max_hops: maxHops,
        top_targets: 10,
      });
      setPathResult(data);
      setPathDrawerOpen(true);
    } catch (err) {
      open?.({
        type: "error",
        message: err instanceof ApiError ? err.detail : String(err),
      });
    } finally {
      setPathLoading(false);
    }
  };

  const pathActions = (
    <Group gap="xs" align="flex-end" wrap="nowrap">
      <NumberInput
        label={t("catalog.joins.path.maxHops")}
        value={maxHops}
        onChange={(v) => setMaxHops(typeof v === "number" ? v : 2)}
        min={1}
        max={5}
        w={110}
        size="sm"
      />
      <Button size="sm" loading={pathLoading} onClick={() => void explorePaths()}>
        {t("catalog.joins.path.explore")}
      </Button>
    </Group>
  );

  return (
    <FillColumn gap="md">
      {writable ? (
        <Stack gap="xs" style={{ flexShrink: 0 }}>
          <Text size="sm" fw={500}>
            {t("catalog.joins.add")}
          </Text>
          <Group align="flex-end" grow>
            <Select
              label={t("catalog.joins.from")}
              data={object.columns.map((c) => ({
                value: c.id,
                label: `${c.name} · ${c.locator_key}`,
              }))}
              value={joinFromId}
              onChange={setJoinFromId}
              searchable
              size="sm"
            />
            <Select
              label={t("catalog.joins.toColumn")}
              data={toOptions}
              value={joinToId}
              onChange={setJoinToId}
              searchable
              searchValue={toSearch}
              onSearchChange={setToSearch}
              filter={({ options }) => options}
              clearable
              size="sm"
              nothingFoundMessage={
                toSearchLoading
                  ? "…"
                  : debouncedToSearch.trim()
                    ? undefined
                    : t("catalog.joins.toColumnPlaceholder")
              }
              placeholder={t("catalog.joins.toColumnPlaceholder")}
            />
          </Group>
          <Group grow>
            <Select
              label={t("catalog.joins.kind")}
              data={["INNER", "LEFT", "RIGHT", "FULL"]}
              value={joinKind}
              onChange={setJoinKind}
              size="sm"
            />
            <Textarea
              label={t("catalog.joins.expression")}
              value={joinExpression}
              onChange={(e) => setJoinExpression(e.currentTarget.value)}
              minRows={1}
              size="sm"
            />
          </Group>
          <Textarea
            label={t("catalog.joins.evidence")}
            value={joinEvidence}
            onChange={(e) => setJoinEvidence(e.currentTarget.value)}
            minRows={1}
            required
            size="sm"
          />
          <Button
            size="sm"
            w="fit-content"
            loading={saving}
            onClick={() => void saveJoinEdge()}
          >
            {t("catalog.joins.save")}
          </Button>
        </Stack>
      ) : null}

      <div style={{ flexShrink: 0 }}>
        <SectionHeader
          title={t("catalog.joins.title")}
          actions={pathActions}
          order={4}
        />
      </div>

      <ListTable
        state={listPresentation.state}
        columnCount={writable ? 8 : 7}
        refreshing={listPresentation.refreshing}
        errorMessage={error}
        onRetry={() => void reload()}
        emptyMessage={t("catalog.joins.empty")}
        head={
          <Table.Tr>
            <Table.Th>{t("catalog.joins.from")}</Table.Th>
            <Table.Th>{t("catalog.joins.to")}</Table.Th>
            <Table.Th>{t("catalog.joins.kind")}</Table.Th>
            <Table.Th>{t("catalog.joins.expression")}</Table.Th>
            <Table.Th>{t("catalog.joins.evidence")}</Table.Th>
            <Table.Th>{t("catalog.joins.origin")}</Table.Th>
            <Table.Th>{t("catalog.joins.createdAt")}</Table.Th>
            {writable ? <Table.Th /> : null}
          </Table.Tr>
        }
        page={page}
        pageSize={pageSize}
        total={total}
        onPageChange={setPage}
      >
        {joins.map((join) => {
          const auto = join.origin === "foreign_key";
          return (
            <Table.Tr key={join.id}>
              <Table.Td>
                <Text size="xs" style={{ wordBreak: "break-all" }}>
                  {join.from_column_locator_key ??
                    columnLabel(object, join.from_column_id)}
                </Text>
              </Table.Td>
              <Table.Td>
                <Text size="xs" style={{ wordBreak: "break-all" }}>
                  {join.to_column_locator_key ??
                    columnLabel(object, join.to_column_id)}
                </Text>
              </Table.Td>
              <Table.Td>{join.join_kind ?? "INNER"}</Table.Td>
              <Table.Td>{join.join_expression ?? "—"}</Table.Td>
              <Table.Td>{join.evidence}</Table.Td>
              <Table.Td>
                <Group gap={4}>
                  <Text size="sm">{join.origin ?? "—"}</Text>
                  {auto ? (
                    <Badge size="xs" color="gray">
                      {t("catalog.joins.autoDerived")}
                    </Badge>
                  ) : null}
                </Group>
              </Table.Td>
              <Table.Td>{join.created_at}</Table.Td>
              {writable ? (
                <Table.Td>
                  {auto ? null : (
                    <Button
                      size="xs"
                      variant="subtle"
                      color="red"
                      loading={saving}
                      onClick={() => void removeJoinEdge(join.id)}
                    >
                      {t("catalog.joins.delete")}
                    </Button>
                  )}
                </Table.Td>
              ) : null}
            </Table.Tr>
          );
        })}
      </ListTable>

      <Drawer
        opened={pathDrawerOpen}
        onClose={() => setPathDrawerOpen(false)}
        title={t("catalog.joins.path.title")}
        position="right"
        size="md"
      >
        {pathResult == null ? null : pathResult.paths.length === 0 ? (
          <Text size="sm" c="dimmed">
            {t("catalog.joins.path.empty")}
          </Text>
        ) : (
          <Stack gap="sm">
            {pathResult.paths.map((path, idx) => (
              <Stack
                key={`${path.target_object_id ?? "t"}-${idx}`}
                gap={4}
                p="sm"
                style={{
                  border: "1px solid var(--mantine-color-gray-3)",
                  borderRadius: 8,
                }}
              >
                <Text size="sm" fw={500}>
                  {t("catalog.joins.path.summary")}: {path.path_summary}
                </Text>
                {path.hops.map((hop) => (
                  <Text key={hop.join_id} size="xs" c="dimmed">
                    {hop.from_column_locator_key} → {hop.to_column_locator_key}{" "}
                    ({hop.join_kind}, {hop.origin})
                  </Text>
                ))}
                {path.target_object_id ? (
                  <Button
                    component={Link}
                    href={`/console/catalog/${path.target_object_id}`}
                    size="xs"
                    variant="light"
                    w="fit-content"
                  >
                    {t("catalog.joins.path.openTarget")}
                  </Button>
                ) : null}
              </Stack>
            ))}
          </Stack>
        )}
      </Drawer>
    </FillColumn>
  );
}
