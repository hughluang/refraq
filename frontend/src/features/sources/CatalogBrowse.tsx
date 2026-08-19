"use client";

import {
  Anchor,
  Badge,
  Button,
  Checkbox,
  CloseButton,
  Group,
  Loader,
  Select,
  Table,
  Text,
  TextInput,
  Tooltip,
} from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ListTable } from "@/components/display/ListTable";
import { EmptyState } from "@/components/feedback/EmptyState";
import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { PageError } from "@/components/feedback/PageError";
import { PageChrome } from "@/components/layout/PageChrome";
import { listCatalogObjects, listSources } from "@/features/sources/api";
import type { Source } from "@/features/sources/types";
import { usePagedList } from "@/hooks/usePagedList";
import { ApiError } from "@/lib/api";
import { listPresentationOf } from "@/lib/list-state";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 100;
const COLUMN_COUNT = 7;

type SemanticsReadyFilter = "all" | "ready" | "not_ready";

export function CatalogBrowse() {
  const t = useTranslate();
  const { open } = useNotification();

  const [sources, setSources] = useState<Source[]>([]);
  const [sourceId, setSourceId] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [semanticsReady, setSemanticsReady] =
    useState<SemanticsReadyFilter>("all");
  const [includeAbsent, setIncludeAbsent] = useState(true);

  const onError = useCallback(
    (message: string) => {
      open?.({ type: "error", message });
    },
    [open],
  );

  const fetchPage = useCallback(
    (query: PageQuery) =>
      listCatalogObjects(sourceId as string, debouncedQ || undefined, {
        ...query,
        include_absent: includeAbsent,
        business_semantics_ready:
          semanticsReady === "all" ? undefined : semanticsReady === "ready",
      }),
    [sourceId, debouncedQ, includeAbsent, semanticsReady],
  );

  const {
    items,
    total,
    page,
    setPage,
    loading: listLoading,
    error: listError,
    reload,
    pageSize,
  } = usePagedList({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
    resetDeps: [sourceId, debouncedQ, includeAbsent, semanticsReady],
    enabled: Boolean(sourceId),
    onError,
  });

  const loadSources = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listSources({ limit: 500 });
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

  useEffect(() => {
    void loadSources();
  }, [loadSources]);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQ(q), 300);
    return () => window.clearTimeout(timer);
  }, [q]);

  const filtersOffDefault =
    q !== "" || semanticsReady !== "all" || !includeAbsent;
  const filtered =
    Boolean(debouncedQ) || semanticsReady !== "all" || !includeAbsent;
  const listPresentation = listPresentationOf({
    loading: listLoading,
    error: listError,
    total,
    itemCount: items.length,
    filtered,
  });

  function clearFilters() {
    setQ("");
    setDebouncedQ("");
    setSemanticsReady("all");
    setIncludeAbsent(true);
  }

  if (error && !loading) return <PageError message={error} />;

  const refreshAction = (
    <Button size="sm" variant="light" onClick={() => void reload()}>
      {t("catalog.refresh")}
    </Button>
  );

  const searchRightSection = listLoading ? (
    <Loader size="xs" />
  ) : q ? (
    <CloseButton
      size="sm"
      aria-label={t("common.search.clear")}
      onClick={() => {
        setQ("");
        setDebouncedQ("");
      }}
    />
  ) : null;

  return (
    <PageChrome
      title={t("catalog.title")}
      description={t("catalog.description")}
      actions={refreshAction}
    >
      {loading && sources.length === 0 ? (
        <PageBodySkeleton />
      ) : sources.length === 0 ? (
        <EmptyState message={t("catalog.list.noSources")} />
      ) : (
        <>
          <Group align="flex-end" wrap="wrap">
            <Select
              label={t("catalog.fields.source")}
              data={sources.map((s) => ({
                value: s.id,
                label: `${s.key} — ${s.name}`,
              }))}
              value={sourceId}
              onChange={(value) => {
                if (value) setSourceId(value);
              }}
              searchable
              allowDeselect={false}
              w={320}
            />
            <TextInput
              label={t("catalog.fields.search")}
              value={q}
              onChange={(e) => setQ(e.currentTarget.value)}
              w={220}
              rightSection={searchRightSection}
              rightSectionPointerEvents={listLoading ? "none" : "auto"}
            />
            <Select
              label={t("catalog.fields.ready")}
              data={[
                {
                  value: "all",
                  label: t("catalog.list.semanticsReady.all"),
                },
                {
                  value: "not_ready",
                  label: t("catalog.list.semanticsReady.notReady"),
                },
                {
                  value: "ready",
                  label: t("catalog.list.semanticsReady.ready"),
                },
              ]}
              value={semanticsReady}
              onChange={(value) =>
                setSemanticsReady(
                  (value as SemanticsReadyFilter | null) ?? "all",
                )
              }
              allowDeselect={false}
              w={180}
            />
            <Checkbox
              label={t("catalog.list.includeAbsent")}
              checked={includeAbsent}
              onChange={(e) => setIncludeAbsent(e.currentTarget.checked)}
              mb={4}
            />
            {filtersOffDefault ? (
              <Button
                variant="subtle"
                size="xs"
                onClick={clearFilters}
                mb={4}
              >
                {t("common.filters.clear")}
              </Button>
            ) : null}
          </Group>

          <ListTable
            state={listPresentation.state}
            columnCount={COLUMN_COUNT}
            refreshing={listPresentation.refreshing}
            errorMessage={listError}
            onRetry={() => void reload()}
            emptyMessage={t("catalog.empty")}
            noMatchMessage={t("catalog.list.noMatch")}
            head={
              <Table.Tr>
                <Table.Th>{t("catalog.fields.schema")}</Table.Th>
                <Table.Th>{t("catalog.fields.name")}</Table.Th>
                <Table.Th>{t("catalog.fields.businessName")}</Table.Th>
                <Table.Th>{t("catalog.fields.type")}</Table.Th>
                <Table.Th>{t("catalog.fields.ready")}</Table.Th>
                <Table.Th>{t("catalog.fields.locator")}</Table.Th>
                <Table.Th>{t("catalog.fields.present")}</Table.Th>
              </Table.Tr>
            }
            page={page}
            pageSize={pageSize}
            total={total}
            onPageChange={setPage}
          >
            {items.map((obj) => (
              <Table.Tr key={obj.id}>
                <Table.Td>{obj.schema_name}</Table.Td>
                <Table.Td>
                  <Anchor
                    component={Link}
                    href={`/console/catalog/${obj.id}`}
                    size="sm"
                  >
                    {obj.name}
                  </Anchor>
                </Table.Td>
                <Table.Td>{obj.business_name ?? "—"}</Table.Td>
                <Table.Td>{obj.object_type}</Table.Td>
                <Table.Td>
                  <Badge
                    variant={obj.business_semantics_ready ? "light" : "outline"}
                    color={obj.business_semantics_ready ? "green" : "gray"}
                  >
                    {obj.business_semantics_ready
                      ? t("catalog.semantics.ready")
                      : t("catalog.semantics.notReady")}
                  </Badge>
                </Table.Td>
                <Table.Td maw={280} style={{ maxWidth: 280, overflow: "hidden" }}>
                  <Tooltip label={obj.locator_key}>
                    <Text size="xs" c="dimmed" truncate>
                      {obj.locator_key}
                    </Text>
                  </Tooltip>
                </Table.Td>
                <Table.Td>
                  {obj.is_present ? (
                    <Text size="sm" c="dimmed">
                      {t("catalog.fields.presentValue")}
                    </Text>
                  ) : (
                    <Badge variant="light" color="orange">
                      {t("catalog.fields.absentValue")}
                    </Badge>
                  )}
                </Table.Td>
              </Table.Tr>
            ))}
          </ListTable>
        </>
      )}
    </PageChrome>
  );
}
