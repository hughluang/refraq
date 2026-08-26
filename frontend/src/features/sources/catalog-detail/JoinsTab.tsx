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
import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import { FillColumn } from "@/components/layout/FillColumn";
import { SectionHeader } from "@/components/layout/SectionHeader";
import { searchCatalogColumns } from "@/features/sources/api/catalog";
import {
  deleteJoin,
  createJoin,
  getJoinPath,
  listObjectJoins,
  patchJoin,
  rejectJoin,
  restoreJoin,
} from "@/features/sources/api/joins";
import {
  type JoinSelectOption,
  columnLabel,
  columnOptionLabel,
  joinDeleteErrorKey,
  joinRowActions,
  joinRowState,
  mergeSelectedOption,
  retainSelectedOption,
  validateJoinDraft,
} from "@/features/sources/catalog-detail/joinEdges";
import type { CatalogObject, JoinPathResult } from "@/features/sources/types";
import { useConfirmAction } from "@/hooks/useConfirmAction";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { useSearchDebounce } from "@/hooks/useSearchDebounce";
import { ApiError } from "@/lib/api";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;

type JoinsTabProps = {
  object: CatalogObject;
  writable: boolean;
  listEnabled?: boolean;
};

export function JoinsTab({
  object,
  writable,
  listEnabled = true,
}: JoinsTabProps) {
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
  const [editingJoinId, setEditingJoinId] = useState<string | null>(null);
  const [toSearch, setToSearch] = useState("");
  const debouncedToSearch = useSearchDebounce(toSearch);
  const [toOptions, setToOptions] = useState<JoinSelectOption[]>([]);
  const [toSearchLoading, setToSearchLoading] = useState(false);
  const [maxHops, setMaxHops] = useState(2);
  const [pathLoading, setPathLoading] = useState(false);
  const [pathResult, setPathResult] = useState<JoinPathResult | null>(null);
  const [pathDrawerOpen, setPathDrawerOpen] = useState(false);
  const deleteConfirm = useConfirmAction<string>();

  const fetchPage = useCallback(
    (query: PageQuery) => listObjectJoins(object.id, query),
    [object.id],
  );
  const list = useConsolePagedList({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
    resetDeps: [object.id],
    enabled: listEnabled,
  });
  const { items: joins, reload } = list;

  useEffect(() => {
    setJoinFromId(object.columns[0]?.id ?? null);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- Overview save must not reset the from-column picker
  }, [object.id]);

  useEffect(() => {
    const query = debouncedToSearch.trim();
    if (!query) {
      setToOptions((prev) => retainSelectedOption(prev, joinToId));
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
          label: columnOptionLabel(c.name, c.locator_key),
        }));
        setToOptions((prev) => mergeSelectedOption(next, joinToId, prev));
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
    const check = validateJoinDraft({
      evidence: joinEvidence,
      fromId: joinFromId,
      toId: joinToId,
    });
    if (!check.ok) {
      open?.({ type: "error", message: t(check.messageKey) });
      return;
    }
    setSaving(true);
    try {
      if (editingJoinId) {
        await patchJoin(editingJoinId, {
          evidence: check.evidence,
          join_kind: joinKind || "INNER",
          join_expression: joinExpression.trim() || null,
        });
      } else {
        await createJoin({
          from_column_id: check.fromId,
          to_column_id: check.toId,
          evidence: check.evidence,
          join_kind: joinKind || "INNER",
          join_expression: joinExpression.trim() || null,
        });
      }
      await reload();
      setJoinEvidence("");
      setJoinExpression("");
      setEditingJoinId(null);
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
      deleteConfirm.close();
      await reload();
      open?.({ type: "success", message: t("catalog.joins.deleted") });
    } catch (err) {
      const messageKey =
        err instanceof ApiError ? joinDeleteErrorKey(err.code) : null;
      open?.({
        type: "error",
        message:
          messageKey != null
            ? t(messageKey)
            : err instanceof ApiError
              ? err.detail
              : String(err),
      });
    } finally {
      setSaving(false);
    }
  };

  const rejectJoinEdge = async (joinId: string) => {
    setSaving(true);
    try {
      await rejectJoin(joinId);
      await reload();
      open?.({ type: "success", message: t("catalog.joins.rejected") });
    } catch (err) {
      open?.({
        type: "error",
        message: err instanceof ApiError ? err.detail : String(err),
      });
    } finally {
      setSaving(false);
    }
  };

  const restoreJoinEdge = async (joinId: string) => {
    setSaving(true);
    try {
      await restoreJoin(joinId);
      await reload();
      open?.({ type: "success", message: t("catalog.joins.restored") });
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
            {editingJoinId
              ? t("catalog.joins.amending")
              : t("catalog.joins.add")}
          </Text>
          <Group align="flex-end" grow>
            <Select
              label={t("catalog.joins.from")}
              data={object.columns.map((c) => ({
                value: c.id,
                label: columnOptionLabel(c.name, c.locator_key),
              }))}
              value={joinFromId}
              onChange={setJoinFromId}
              searchable
              size="sm"
              disabled={editingJoinId != null}
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
              disabled={editingJoinId != null}
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
        list={list}
        columnCount={writable ? 8 : 7}
        emptyMessage={t("catalog.joins.empty")}
        head={
          <Table.Tr>
            <Table.Th>{t("catalog.joins.from")}</Table.Th>
            <Table.Th>{t("catalog.joins.to")}</Table.Th>
            <Table.Th>{t("catalog.joins.kind")}</Table.Th>
            <Table.Th>{t("catalog.joins.expression")}</Table.Th>
            <Table.Th>{t("catalog.joins.evidence")}</Table.Th>
            <Table.Th>{t("catalog.joins.state")}</Table.Th>
            <Table.Th>{t("catalog.joins.createdAt")}</Table.Th>
            {writable ? <Table.Th /> : null}
          </Table.Tr>
        }
      >
        {joins.map((join) => {
          const state = joinRowState(join);
          const actions = joinRowActions(state);
          return (
            <Table.Tr key={join.id}>
              <Table.Td>
                <Text size="xs" style={{ wordBreak: "break-all" }}>
                  {join.from_column_locator_key ??
                    columnLabel(object.columns, join.from_column_id)}
                </Text>
              </Table.Td>
              <Table.Td>
                <Text size="xs" style={{ wordBreak: "break-all" }}>
                  {join.to_column_locator_key ??
                    columnLabel(object.columns, join.to_column_id)}
                </Text>
              </Table.Td>
              <Table.Td>{join.join_kind ?? "INNER"}</Table.Td>
              <Table.Td>{join.join_expression ?? "—"}</Table.Td>
              <Table.Td>{join.evidence}</Table.Td>
              <Table.Td>
                <Group gap={4}>
                  {state === "rejected" ? (
                    <Badge size="xs" color="red">
                      {t("catalog.joins.state.rejected")}
                    </Badge>
                  ) : state === "automated" ? (
                    <Badge size="xs" color="gray">
                      {t("catalog.joins.state.automated")}
                    </Badge>
                  ) : (
                    <Badge size="xs" color="blue">
                      {t("catalog.joins.state.manual")}
                    </Badge>
                  )}
                </Group>
              </Table.Td>
              <Table.Td>{join.created_at}</Table.Td>
              {writable ? (
                <Table.Td>
                  <Group gap={4} wrap="nowrap">
                    {actions.restore ? (
                      <Button
                        size="xs"
                        variant="subtle"
                        loading={saving}
                        onClick={() => void restoreJoinEdge(join.id)}
                      >
                        {t("catalog.joins.restore")}
                      </Button>
                    ) : (
                      <>
                        {actions.amend ? (
                          <Button
                            size="xs"
                            variant="subtle"
                            loading={saving}
                            onClick={() => {
                              setEditingJoinId(join.id);
                              setJoinFromId(join.from_column_id);
                              setJoinToId(join.to_column_id);
                              setToOptions((prev) =>
                                mergeSelectedOption(
                                  prev,
                                  join.to_column_id,
                                  [
                                    {
                                      value: join.to_column_id,
                                      label:
                                        join.to_column_locator_key ??
                                        join.to_column_id,
                                    },
                                  ],
                                ),
                              );
                              setJoinKind(join.join_kind ?? "INNER");
                              setJoinExpression(join.join_expression ?? "");
                              setJoinEvidence(join.evidence);
                            }}
                          >
                            {t("catalog.joins.amend")}
                          </Button>
                        ) : null}
                        {actions.reject ? (
                          <Button
                            size="xs"
                            variant="subtle"
                            color="orange"
                            loading={saving}
                            onClick={() => void rejectJoinEdge(join.id)}
                          >
                            {t("catalog.joins.reject")}
                          </Button>
                        ) : null}
                        {actions.delete ? (
                          <Button
                            size="xs"
                            variant="subtle"
                            color="red"
                            loading={saving}
                            onClick={() => deleteConfirm.open(join.id)}
                          >
                            {t("catalog.joins.delete")}
                          </Button>
                        ) : null}
                      </>
                    )}
                  </Group>
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
                    ({hop.join_kind})
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
      <ConfirmActionModal
        opened={deleteConfirm.opened}
        onClose={deleteConfirm.close}
        title={t("catalog.joins.deleteConfirm.title")}
        body={t("catalog.joins.deleteConfirm.body")}
        confirmColor="red"
        loading={saving}
        confirmLabel={t("catalog.joins.delete")}
        onConfirm={() => {
          if (deleteConfirm.pending != null) {
            void removeJoinEdge(deleteConfirm.pending);
          }
        }}
      />
    </FillColumn>
  );
}
