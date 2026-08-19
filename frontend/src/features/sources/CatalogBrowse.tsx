"use client";

import {
  Badge,
  Button,
  Checkbox,
  Group,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ListPager } from "@/components/display/ListPager";
import { EmptyState } from "@/components/feedback/EmptyState";
import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { PageError } from "@/components/feedback/PageError";
import { PageChrome } from "@/components/layout/PageChrome";
import { listCatalogObjects, listSources } from "@/features/sources/api";
import type { Source } from "@/features/sources/types";
import { usePagedList } from "@/hooks/usePagedList";
import { ApiError } from "@/lib/api";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 100;

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

  if (error && !loading) return <PageError message={error} />;

  const refreshAction = (
    <Button size="sm" variant="light" onClick={() => void reload()}>
      {t("catalog.refresh")}
    </Button>
  );

  return (
    <PageChrome
      title={t("catalog.title")}
      description={t("catalog.description")}
      actions={refreshAction}
    >
      {loading && sources.length === 0 ? (
        <PageBodySkeleton />
      ) : (
        <>
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
                setSemanticsReady((value as SemanticsReadyFilter | null) ?? "all")
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
          </Group>

          {listLoading && items.length === 0 ? (
            <PageBodySkeleton />
          ) : listError && items.length === 0 ? (
            <PageError message={listError} onRetry={() => void reload()} />
          ) : !sourceId || total === 0 ? (
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
                  {items.map((obj) => (
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
              <ListPager
                page={page}
                pageSize={pageSize}
                total={total}
                onChange={setPage}
              />
            </Stack>
          )}
        </>
      )}
    </PageChrome>
  );
}
