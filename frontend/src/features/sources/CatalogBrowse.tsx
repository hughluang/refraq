"use client";

import { Button, Group, Table, Text, Tooltip } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useCallback, useEffect, useState } from "react";

import { ListTable } from "@/components/display/ListTable";
import { ListToolbar } from "@/components/display/ListToolbar";
import { RecordReference } from "@/components/display/RecordReference";
import { StatusBadge } from "@/components/display/StatusBadge";
import {
  presentCatalogPresence,
  presentCatalogSemantics,
} from "@/components/display/statusTone";
import { EmptyState } from "@/components/feedback/EmptyState";
import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { PageError } from "@/components/feedback/PageError";
import { RecordPicker } from "@/components/form/RecordPicker";
import { sourceRecordAdapter } from "@/components/form/recordPickerAdapters";
import { PageChrome } from "@/components/layout/PageChrome";
import { listCatalogObjects } from "@/features/sources/api/catalog";
import { objectTypeLabel } from "@/features/sources/catalogLabel";
import { listSources } from "@/features/sources/api/sources";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { useListQuery } from "@/hooks/useListQuery";
import { problemMessage } from "@/lib/problem";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 100;
const COLUMN_COUNT = 7;

export function CatalogBrowse() {
  const t = useTranslate();
  const query = useListQuery({
    filters: [
      { key: "source", type: "select", defaultValue: "" },
      { key: "ready", type: "select", defaultValue: "" },
      { key: "absent", type: "select", defaultValue: "" },
    ],
  });
  const ready = query.select("ready");
  const absent = query.select("absent");

  const urlSource = query.select("source");
  const [fallbackId, setFallbackId] = useState<string | null>(null);
  const [phase, setPhase] = useState<"loading" | "empty" | "ready" | "error">(
    urlSource ? "ready" : "loading",
  );
  const [error, setError] = useState<string | null>(null);
  const sourceId = urlSource || fallbackId;

  const fetchPage = useCallback(
    (page: PageQuery) =>
      listCatalogObjects(sourceId as string, query.search || undefined, {
        ...page,
        include_absent: absent !== "present",
        business_semantics_ready:
          ready === "ready" ? true : ready === "not_ready" ? false : undefined,
      }),
    [sourceId, query.search, absent, ready],
  );

  const objectFiltered =
    query.search !== "" ||
    ready === "ready" ||
    ready === "not_ready" ||
    absent === "present";
  const list = useConsolePagedList({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
    resetDeps: [sourceId, query.search, absent, ready],
    enabled: Boolean(sourceId),
    filtered: objectFiltered,
    page: query.page,
    onPageChange: query.setPage,
  });
  const { items, reload } = list;

  useEffect(() => {
    if (urlSource || fallbackId) {
      setPhase("ready");
      return;
    }
    let cancelled = false;
    setPhase("loading");
    listSources({ limit: 1, offset: 0 })
      .then((data) => {
        if (cancelled) return;
        const first = data.items[0];
        if (!first) {
          setPhase("empty");
          return;
        }
        setFallbackId(first.id);
        setError(null);
        setPhase("ready");
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setPhase("error");
          setError(problemMessage(t, err, String(err)));
        }
      });
    return () => {
      cancelled = true;
    };
  }, [fallbackId, t, urlSource]);

  if (phase === "error" && error) return <PageError message={error} />;

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
      toolbar={
        phase === "ready" && sourceId ? (
          <Group align="flex-end" wrap="wrap">
            <RecordPicker
              editable
              label={t("catalog.fields.source")}
              adapter={sourceRecordAdapter()}
              value={sourceId}
              w={320}
              onChange={(value) => {
                if (value) query.setFilter("source", value);
              }}
            />
            <ListToolbar
              query={query}
              searchPlaceholder={t("catalog.fields.search")}
              filters={[
                {
                  key: "ready",
                  label: t("catalog.fields.ready"),
                  options: [
                    {
                      value: "not_ready",
                      label: t("catalog.list.semanticsReady.notReady"),
                    },
                    {
                      value: "ready",
                      label: t("catalog.list.semanticsReady.ready"),
                    },
                  ],
                },
                {
                  key: "absent",
                  label: t("catalog.fields.present"),
                  options: [
                    {
                      value: "present",
                      label: t("catalog.list.presentOnly"),
                    },
                  ],
                },
              ]}
            />
          </Group>
        ) : undefined
      }
    >
      {phase === "loading" ? (
        <PageBodySkeleton />
      ) : phase === "empty" ? (
        <EmptyState message={t("catalog.list.noSources")} />
      ) : (
        <>
          <ListTable
            list={list}
            columnCount={COLUMN_COUNT}
            emptyMessage={t("catalog.empty")}
            noMatchMessage={t("catalog.list.noMatch")}
            onClearFilters={query.clear}
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
          >
            {items.map((obj) => {
              const ready = presentCatalogSemantics(
                Boolean(obj.business_semantics_ready),
              );
              const presence = presentCatalogPresence(obj.is_present);
              return (
              <Table.Tr key={obj.id}>
                <Table.Td>{obj.schema_name}</Table.Td>
                <Table.Td>
                  <RecordReference
                    name={obj.name}
                    recordKey={obj.schema_name}
                    href={`/console/catalog/${obj.id}`}
                  />
                </Table.Td>
                <Table.Td>{obj.business_name ?? "—"}</Table.Td>
                <Table.Td>{objectTypeLabel(t, obj.object_type)}</Table.Td>
                <Table.Td>
                  <StatusBadge tone={ready.tone} labelKey={ready.labelKey} />
                </Table.Td>
                <Table.Td maw={280} style={{ maxWidth: 280, overflow: "hidden" }}>
                  <Tooltip label={obj.locator_key}>
                    <Text size="xs" c="dimmed" truncate>
                      {obj.locator_key}
                    </Text>
                  </Tooltip>
                </Table.Td>
                <Table.Td>
                  <StatusBadge tone={presence.tone} labelKey={presence.labelKey} />
                </Table.Td>
              </Table.Tr>
              );
            })}
          </ListTable>
        </>
      )}
    </PageChrome>
  );
}
