"use client";

import { Anchor, Button, Group, Table, Text, Tooltip } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useCallback, useEffect, useRef, useState } from "react";

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
import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { RecordPicker } from "@/components/form/RecordPicker";
import { catalogSourceAdapter } from "@/components/form/recordPickerAdapters";
import { PageChrome } from "@/components/layout/PageChrome";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { listCatalogObjects, listCatalogSources } from "@/features/sources/api/catalog";
import { MirrorTableDrawer } from "@/features/mirrors/MirrorTableDrawer";
import { listSourceSchedules, runSchedule } from "@/features/schedules/api";
import { ApiError } from "@/lib/api";
import { ForbiddenState } from "@/components/feedback/ForbiddenState";
import {
  objectCategoryLabel,
  objectTypeLabel,
} from "@/features/sources/catalogLabel";
import type { CatalogObject } from "@/features/sources/types";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { useListQuery } from "@/hooks/useListQuery";
import type { PageQuery } from "@/lib/pagination";

function CollectStructure({ sourceId }: { sourceId: string }) {
  const t = useTranslate();
  const [schedule, setSchedule] = useState("");
  const [state, setState] = useState<"loading" | "contact" | "ready" | "error" | "running" | "queued">("loading");
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    let current = true;
    async function discover() {
      for (let offset = 0; ; ) {
        const page = await listSourceSchedules(sourceId, { limit: 100, offset });
        if (!current) return;
        const structure = page.items.find(item => item.work_kind === "structure");
        if (structure) {
          setSchedule(structure.id);
          setState("ready");
          return;
        }
        offset += page.items.length;
        if (!page.items.length || offset >= page.total) {
          setState("contact");
          return;
        }
      }
    }
    setState("loading");
    void discover().catch((err: unknown) => {
      if (current) setState(err instanceof ApiError && [403, 404].includes(err.status) ? "contact" : "error");
    });
    return () => { current = false; };
  }, [sourceId, attempt]);
  if (state === "loading") return null;
  if (state === "contact" || state === "queued") return <Text size="sm">{t(`catalog.collect.${state}`)}</Text>;
  if (state === "error") return <Button variant="light" onClick={() => setAttempt(attempt + 1)}>{t("common.retry")}</Button>;
  async function collect() {
    setState("running");
    try {
      await runSchedule(schedule);
      setState("queued");
    } catch (err) {
      setState(err instanceof ApiError && [403, 404].includes(err.status) ? "contact" : "ready");
      presentProblemNotification(t, err);
    }
  }
  return <Button variant="light" loading={state === "running"} onClick={() => void collect()}>{t("catalog.collect.action")}</Button>;
}

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
  const [phase, setPhase] = useState<"loading" | "empty" | "ready" | "unloaded" | "restricted">(
    urlSource ? "ready" : "loading",
  );
  const sourceId = urlSource || fallbackId;
  const probeGeneration = useRef(0);

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

  const load = useCallback(() => {
    const generation = ++probeGeneration.current;
    if (urlSource || fallbackId) {
      setPhase("ready");
      return;
    }
    setPhase("loading");
    void listCatalogSources({ limit: 1, offset: 0 })
      .then((data) => {
        if (generation !== probeGeneration.current) return;
        const first = data.items[0];
        if (!first) {
          setPhase("empty");
          return;
        }
        setFallbackId(first.id);
        setPhase("ready");
      })
      .catch((err: unknown) => {
        if (generation !== probeGeneration.current) return;
        if (err instanceof ApiError && [403, 404].includes(err.status)) {
          setPhase("restricted");
          return;
        }
        setPhase("unloaded");
        presentProblemNotification(t, err, { onRetry: () => void load() });
      });
  }, [fallbackId, t, urlSource]);

  useEffect(() => {
    load();
    return () => {
      probeGeneration.current += 1;
    };
  }, [load]);

  const clearObjectFilters = () => {
    query.clear();
    if (urlSource) query.setFilter("source", urlSource);
  };
  const refreshAction = (
    <Button size="sm" variant="light" onClick={() => sourceId ? void reload() : load()}>
      {t("catalog.refresh")}
    </Button>
  );

  if (phase === "restricted" || list.errorStatus === 403) return <ForbiddenState reason="metadata:read" />;
  return (
    <PageChrome
      title={t("catalog.title")}
      description={t("catalog.description")}
      actions={<Group gap="sm">
        <MirrorTableDrawer sourceId={sourceId ?? undefined} />
        {refreshAction}
      </Group>}
      status={phase === "unloaded" ? "unloaded" : undefined}
      onRetry={phase === "unloaded" ? () => void load() : undefined}
      toolbar={
        phase === "ready" && sourceId ? (
          <Group align="flex-end" wrap="wrap">
            <RecordPicker
              editable
              label={t("catalog.fields.source")}
              adapter={catalogSourceAdapter}
              value={sourceId}
              w={320}
              onChange={(value) => {
                if (value) query.setFilter("source", value);
              }}
            />
            <ListToolbar
              query={{ ...query, clear: clearObjectFilters, isFiltered: objectFiltered }}
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
      ) : phase === "unloaded" ? null : list.errorStatus === 404 ? (
        <EmptyState message={t("catalog.list.sourceUnavailable")} />
      ) : (
        <>
          <ListTable
            list={list}
            columnCount={COLUMN_COUNT}
            emptyMessage={t("catalog.empty")}
            noMatchMessage={t("catalog.list.noMatch")}
            emptyAction={sourceId && <CollectStructure key={sourceId} sourceId={sourceId} />}
            onClearFilters={clearObjectFilters}
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
