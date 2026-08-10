"use client";

import {
  Badge,
  Button,
  Checkbox,
  Group,
  Pagination,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import { EmptyState } from "@/components/feedback/EmptyState";
import { PageError } from "@/components/feedback/PageError";
import { PageLoader } from "@/components/feedback/PageLoader";
import { PageChrome } from "@/components/layout/PageChrome";
import { listCatalogObjects, listSources } from "@/features/sources/api";
import type { CatalogObject, Source } from "@/features/sources/types";
import { ApiError } from "@/lib/api";

const PAGE_SIZE = 100;

export function CatalogBrowse() {
  const t = useTranslate();
  const { open } = useNotification();

  const [sources, setSources] = useState<Source[]>([]);
  const [sourceId, setSourceId] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [items, setItems] = useState<CatalogObject[]>([]);
  const [listLoading, setListLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [onlyNotReady, setOnlyNotReady] = useState(false);
  const [includeAbsent, setIncludeAbsent] = useState(true);

  const loadSources = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listSources();
      setSources(data.items);
      if (!sourceId && data.items[0]) {
        setSourceId(data.items[0].id);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err));
    } finally {
      setLoading(false);
    }
  }, [sourceId]);

  const loadObjects = useCallback(async () => {
    if (!sourceId) {
      setItems([]);
      setTotal(0);
      return;
    }
    setListLoading(true);
    try {
      const offset = (page - 1) * PAGE_SIZE;
      const data = await listCatalogObjects(sourceId, debouncedQ || undefined, {
        limit: PAGE_SIZE,
        offset,
        include_absent: includeAbsent,
      });
      setItems(data.items);
      setTotal(data.total);
    } catch (err) {
      open?.({
        type: "error",
        message: err instanceof ApiError ? err.detail : String(err),
      });
    } finally {
      setListLoading(false);
    }
  }, [sourceId, debouncedQ, page, includeAbsent, open]);

  useEffect(() => {
    void loadSources();
  }, [loadSources]);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQ(q), 300);
    return () => window.clearTimeout(timer);
  }, [q]);

  useEffect(() => {
    setPage(1);
  }, [sourceId, debouncedQ, includeAbsent]);

  useEffect(() => {
    void loadObjects();
  }, [loadObjects]);

  const visibleItems = useMemo(() => {
    if (!onlyNotReady) return items;
    return items.filter((obj) => !obj.business_semantics_ready);
  }, [items, onlyNotReady]);

  if (loading) return <PageLoader />;
  if (error) return <PageError message={error} />;

  const refreshAction = (
    <Button size="sm" variant="light" onClick={() => void loadObjects()}>
      {t("catalog.refresh")}
    </Button>
  );

  return (
    <PageChrome
      title={t("catalog.title")}
      description={t("catalog.description")}
      actions={refreshAction}
    >
      <Group mb="md" align="flex-end" wrap="wrap">
        <Select
          label={t("catalog.fields.source")}
          data={sources.map((s) => ({
            value: s.id,
            label: `${s.key} — ${s.name}`,
          }))}
          value={sourceId}
          onChange={setSourceId}
          searchable
          w={320}
        />
        <TextInput
          label={t("catalog.fields.search")}
          value={q}
          onChange={(e) => setQ(e.currentTarget.value)}
          w={220}
          rightSection={listLoading ? <Text size="xs">…</Text> : null}
        />
        <Checkbox
          label={t("catalog.list.onlyNotReady")}
          checked={onlyNotReady}
          onChange={(e) => setOnlyNotReady(e.currentTarget.checked)}
          mb={4}
        />
        <Checkbox
          label={t("catalog.list.includeAbsent")}
          checked={includeAbsent}
          onChange={(e) => setIncludeAbsent(e.currentTarget.checked)}
          mb={4}
        />
      </Group>

      {!sourceId || total === 0 ? (
        <EmptyState message={t("catalog.empty")} />
      ) : (
        <Stack gap="sm">
          <Table striped highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t("catalog.fields.schema")}</Table.Th>
                <Table.Th>{t("catalog.fields.name")}</Table.Th>
                <Table.Th>{t("catalog.fields.businessName")}</Table.Th>
                <Table.Th>{t("catalog.fields.type")}</Table.Th>
                <Table.Th>{t("catalog.fields.ready")}</Table.Th>
                <Table.Th>{t("catalog.fields.locator")}</Table.Th>
                <Table.Th>{t("catalog.fields.present")}</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {visibleItems.map((obj) => (
                <Table.Tr key={obj.id}>
                  <Table.Td>{obj.schema_name}</Table.Td>
                  <Table.Td>{obj.name}</Table.Td>
                  <Table.Td>{obj.business_name ?? "—"}</Table.Td>
                  <Table.Td>{obj.object_type}</Table.Td>
                  <Table.Td>
                    <Badge
                      color={obj.business_semantics_ready ? "green" : "gray"}
                    >
                      {obj.business_semantics_ready
                        ? t("catalog.semantics.ready")
                        : t("catalog.semantics.notReady")}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    <Text
                      size="xs"
                      c="dimmed"
                      style={{ wordBreak: "break-all" }}
                    >
                      {obj.locator_key}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Badge color={obj.is_present ? "green" : "gray"}>
                      {obj.is_present
                        ? t("catalog.fields.presentValue")
                        : t("catalog.fields.absentValue")}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    <Button
                      component={Link}
                      href={`/console/catalog/${obj.id}`}
                      size="xs"
                      variant="light"
                    >
                      {t("catalog.detail")}
                    </Button>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
          <Group justify="space-between">
            <Text size="sm" c="dimmed">
              {t("catalog.list.showing", {
                from: (page - 1) * PAGE_SIZE + 1,
                to: Math.min(page * PAGE_SIZE, total),
                total,
              })}
            </Text>
            <Pagination
              value={page}
              onChange={setPage}
              total={Math.max(1, Math.ceil(total / PAGE_SIZE))}
            />
          </Group>
        </Stack>
      )}
    </PageChrome>
  );
}
