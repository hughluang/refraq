"use client";

import { Anchor, Button, Group, Table, Text, Tooltip } from "@mantine/core";
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
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { listCatalogObjects } from "@/features/sources/api/catalog";
import { listSources } from "@/features/sources/api/sources";
import {
  objectCategoryLabel,
  objectTypeLabel,
} from "@/features/sources/catalogLabel";
import type { CatalogObject } from "@/features/sources/types";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { useListQuery } from "@/hooks/useListQuery";
import { problemMessage } from "@/lib/problem";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 100;
const COLUMN_COUNT = 7;
const OBJECT_TYPES = [
  "table",
  "view",
  "materialized_view",
  "procedure",
  "function",
] as const;

function ObjectName({ object }: { object: CatalogObject }) {
  const href = `/console/catalog/${object.id}`;
  const business = object.business_name?.trim() ?? "";
  if (business && business !== object.name) {
    return (
      <RecordReference name={business} recordKey={object.name} href={href} />
    );
  }
  return (
    <Anchor component={ConsoleLink} href={href} size="sm">
      {object.name}
    </Anchor>
  );
}

function ClippedText({ value }: { value: string | null | undefined }) {
  const text = value?.trim() ?? "";
  if (!text) return "—";
  return (
    <Tooltip label={text} multiline maw={360}>
      <Text size="sm" truncate maw={280}>
        {text}
      </Text>
    </Tooltip>
  );
}

export function CatalogBrowse() {
  const t = useTranslate();
  const query = useListQuery({
    filters: [
      { key: "source", type: "select", defaultValue: "" },
      { key: "object_type", type: "select", defaultValue: "" },
      { key: "ready", type: "select", defaultValue: "" },
      { key: "absent", type: "select", defaultValue: "" },
    ],
  });
  const ready = query.select("ready");
  const absent = query.select("absent");
  const objectType = query.select("object_type");

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
        object_type: objectType || undefined,
        include_absent: absent !== "present",
        business_semantics_ready:
          ready === "ready" ? true : ready === "not_ready" ? false : undefined,
      }),
    [sourceId, query.search, absent, ready, objectType],
  );

  const objectFiltered =
    query.search !== "" ||
    objectType !== "" ||
    ready === "ready" ||
    ready === "not_ready" ||
    absent === "present";
  const list = useConsolePagedList({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
    resetDeps: [sourceId, query.search, absent, ready, objectType],
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
                  key: "object_type",
                  label: t("catalog.fields.type"),
                  options: OBJECT_TYPES.map((value) => ({
                    value,
                    label: objectTypeLabel(t, value),
                  })),
                },
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
                <Table.Th>{t("catalog.fields.name")}</Table.Th>
                <Table.Th>{t("catalog.fields.comment")}</Table.Th>
                <Table.Th>{t("catalog.semantics.businessDescription")}</Table.Th>
                <Table.Th>{t("catalog.fields.type")}</Table.Th>
                <Table.Th>{t("catalog.semantics.category")}</Table.Th>
                <Table.Th>{t("catalog.fields.ready")}</Table.Th>
                <Table.Th>{t("catalog.fields.present")}</Table.Th>
              </Table.Tr>
            }
          >
            {items.map((obj) => {
              const semantics = presentCatalogSemantics(
                Boolean(obj.business_semantics_ready),
              );
              const presence = presentCatalogPresence(obj.is_present);
              const category = obj.object_category
                ? objectCategoryLabel(t, obj.object_category)
                : "—";
              return (
                <Table.Tr key={obj.id}>
                  <Table.Td>
                    <ObjectName object={obj} />
                  </Table.Td>
                  <Table.Td maw={280}>
                    <ClippedText value={obj.comment} />
                  </Table.Td>
                  <Table.Td maw={280}>
                    <ClippedText value={obj.business_description} />
                  </Table.Td>
                  <Table.Td>{objectTypeLabel(t, obj.object_type)}</Table.Td>
                  <Table.Td>{category}</Table.Td>
                  <Table.Td>
                    <StatusBadge
                      tone={semantics.tone}
                      labelKey={semantics.labelKey}
                    />
                  </Table.Td>
                  <Table.Td>
                    <StatusBadge
                      tone={presence.tone}
                      labelKey={presence.labelKey}
                    />
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
