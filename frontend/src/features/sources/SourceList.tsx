"use client";

import { Table } from "@mantine/core";
import { useCan, useTranslate } from "@refinedev/core";
import { useCallback } from "react";

import { CreateListAction } from "@/components/access/CreateListAction";
import { ListTable } from "@/components/display/ListTable";
import { ListToolbar } from "@/components/display/ListToolbar";
import { RecordReference } from "@/components/display/RecordReference";
import { RowActions } from "@/components/display/RowActions";
import { StatusBadge } from "@/components/display/StatusBadge";
import { presentSourceStatus } from "@/components/display/statusTone";
import { PageChrome } from "@/components/layout/PageChrome";
import { useConsoleNavigation } from "@/components/navigation/useConsoleNavigation";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import { deleteSource, listSources } from "@/features/sources/api/sources";
import { engineLabel, selectedEngine, SOURCE_ENGINES } from "@/features/sources/engineLabel";
import {
  sourceDiffsPath,
  sourceEditPath,
} from "@/features/sources/sourceRecordTab";
import type { Source } from "@/features/sources/types";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { useListQuery } from "@/hooks/useListQuery";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 100;

function scopeLabel(source: Source): string {
  const access = source.access;
  if (!access || typeof access !== "object") return "—";
  const database = access.database;
  const service = access.service_name;
  if (typeof database === "string" && database.trim()) return database;
  if (typeof service === "string" && service.trim()) return service;
  return "—";
}

export function SourceList() {
  const t = useTranslate();
  const { push } = useConsoleNavigation();
  const engineOptions = SOURCE_ENGINES.map((value) => ({
    value,
    label: engineLabel(t, value),
  }));
  const { data: canWrite } = useCan({
    resource: ModuleId.sources,
    action: ModuleAction.create,
  });
  const { data: canRunJobs } = useCan({
    resource: ModuleId.jobs,
    action: ModuleAction.list,
  });
  const { data: canShow } = useCan({
    resource: ModuleId.sources,
    action: ModuleAction.show,
  });
  const query = useListQuery({
    filters: [{ key: "engine", type: "select", defaultValue: "" }],
  });
  const engine = query.select("engine");
  const showActions = Boolean(canWrite?.can || canRunJobs?.can || canShow?.can);
  const fetchPage = useCallback(
    (page: PageQuery) =>
      listSources({
        ...page,
        q: query.search || undefined,
        engine: selectedEngine(engine),
      }),
    [query.search, engine],
  );
  const list = useConsolePagedList({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
    resetDeps: [query.search, engine],
    filtered: query.isFiltered,
    page: query.page,
    onPageChange: query.setPage,
  });
  const createAction = (
    <CreateListAction resource={ModuleId.sources} href="/console/sources/new">
      {t("sources.create")}
    </CreateListAction>
  );

  return (
    <PageChrome
      title={t("sources.title")}
      description={t("sources.description")}
      actions={createAction}
      toolbar={
        <ListToolbar
          query={query}
          searchPlaceholder={t("sources.search")}
          filters={[
            {
              key: "engine",
              label: t("sources.fields.engine"),
              options: engineOptions,
            },
          ]}
        />
      }
    >
      <ListTable
        list={list}
        columnCount={showActions ? 7 : 6}
        emptyMessage={t("sources.empty")}
        emptyAction={createAction}
        noMatchMessage={t("sources.list.noMatch")}
        onClearFilters={query.clear}
        head={
          <Table.Tr>
            <Table.Th>{t("sources.fields.name")}</Table.Th>
            <Table.Th>{t("sources.fields.engine")}</Table.Th>
            <Table.Th>{t("sources.fields.host")}</Table.Th>
            <Table.Th>{t("sources.fields.database")}</Table.Th>
            <Table.Th>{t("sources.fields.status")}</Table.Th>
            <Table.Th>{t("sources.fields.hasAccess")}</Table.Th>
            {showActions ? <Table.Th>{t("sources.fields.actions")}</Table.Th> : null}
          </Table.Tr>
        }
      >
        {list.items.map((source) => (
          <Table.Tr key={source.id}>
            <Table.Td>
              <RecordReference
                name={source.name}
                recordKey={source.key}
                href={canShow?.can ? `/console/sources/${source.id}` : undefined}
              />
            </Table.Td>
            <Table.Td>{source.engine ? engineLabel(t, source.engine) : "—"}</Table.Td>
            <Table.Td>
              {typeof source.access?.host === "string" ? source.access.host : "—"}
            </Table.Td>
            <Table.Td>{scopeLabel(source)}</Table.Td>
            <Table.Td>
              <StatusBadge
                tone={presentSourceStatus(source.status).tone}
                labelKey={presentSourceStatus(source.status).labelKey}
              />
            </Table.Td>
            <Table.Td>
              {source.has_access
                ? t("sources.fields.hasAccessYes")
                : t("sources.fields.hasAccessNo")}
            </Table.Td>
            {showActions ? (
              <Table.Td>
                <RowActions
                  recordName={source.name}
                  verbs={[
                    {
                      key: "diffs",
                      label: t("structureDiffs.open"),
                      hidden: !canShow?.can,
                      safety: "immediate",
                      onClick: () => push(sourceDiffsPath(source.id)),
                    },
                    {
                      key: "schedules",
                      label: t("schedules.related.open"),
                      hidden: !canRunJobs?.can,
                      safety: "immediate",
                      onClick: () => push(`/console/sources/${source.id}/schedules`),
                    },
                    {
                      key: "edit",
                      label: t("sources.edit"),
                      hidden: !canWrite?.can,
                      safety: "immediate",
                      onClick: () => push(sourceEditPath(source.id)),
                    },
                    {
                      key: "delete",
                      label: t("sources.delete"),
                      color: "red",
                      hidden: !canWrite?.can,
                      disabledReason:
                        source.status === "disabled"
                          ? undefined
                          : t("sources.delete.disabledHint"),
                      action: {
                        safety: "confirm",
                        recordName: source.name,
                        title: t("sources.delete.confirmTitle"),
                        consequence: t("sources.delete.consequence"),
                        confirmLabel: t("sources.delete"),
                        confirmColor: "red",
                        outcome: t("sources.delete.success"),
                        execute: () => deleteSource(source.id),
                        onSuccess: () => list.reload(),
                      },
                    },
                  ]}
                />
              </Table.Td>
            ) : null}
          </Table.Tr>
        ))}
      </ListTable>
    </PageChrome>
  );
}
