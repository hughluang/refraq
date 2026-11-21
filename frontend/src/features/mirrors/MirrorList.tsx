"use client";

import { Button, Table, TextInput } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useCallback } from "react";
import { ForbiddenState } from "@/components/feedback/ForbiddenState";
import { ListTable } from "@/components/display/ListTable";
import { ListToolbar } from "@/components/display/ListToolbar";
import { PageChrome } from "@/components/layout/PageChrome";
import { HeaderActions } from "@/components/layout/HeaderActions";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { useListQuery } from "@/hooks/useListQuery";
import type { PageQuery } from "@/lib/pagination";
import { MirrorEvent, MirrorNextAction } from "./MirrorEvidence";
import { listMirrors } from "./api";
import { MIRROR_STATUSES } from "./types";

const filters = [
  { key: "source_id", type: "select", defaultValue: "" },
  { key: "status", type: "select", defaultValue: "", accept: ["", ...MIRROR_STATUSES] },
] as const;

export function MirrorList() {
  const t = useTranslate();
  const query = useListQuery({ filters });
  const source = query.select("source_id");
  const status = query.select("status");
  const search = query.search;
  const fetchPage = useCallback((page: PageQuery) => listMirrors({ ...page, source_id: source, status, q: search }), [source, status, search]);
  const list = useConsolePagedList({ pageSize: 50, fetch: fetchPage, page: query.page, onPageChange: query.setPage, filtered: query.isFiltered });
  if (list.accessDenied) return <ForbiddenState reason="mirror:read" />;
  return <PageChrome title={t("mirrors.title")} description={t("mirrors.description")}
    actions={<HeaderActions navigation={<Button size="sm" variant="light" onClick={() => void list.reload()}>{t("common.refresh")}</Button>} />}
    toolbar={<ListToolbar query={query} filters={[{ key: "status", label: t("mirrors.status"), options: MIRROR_STATUSES.map(value => ({ value, label: t(`mirrors.status.${value}`) })) }]}
      extra={<TextInput aria-label={t("mirrors.sourceFilter")} placeholder={t("mirrors.sourceFilter")} value={source} onChange={event => query.setFilter("source_id", event.currentTarget.value)} />} />}>
    <ListTable list={list}
      emptyMessage={t("mirrors.empty")}
      columnCount={5} onClearFilters={query.clear}
      head={<Table.Tr>{["source", "object", "desiredState", "lastEvent", "nextAction"].map(key => <Table.Th key={key}>{t(`mirrors.${key}`)}</Table.Th>)}</Table.Tr>}>
      {list.items.map(mirror => <Table.Tr key={mirror.id}>
        <Table.Td>{mirror.source_name ?? mirror.source_key ?? mirror.source_id}</Table.Td>
        <Table.Td><ConsoleLink href={`/console/mirrors/${encodeURIComponent(mirror.id)}`}>{mirror.qualified_table}</ConsoleLink></Table.Td>
        <Table.Td>{t(mirror.enabled ? "mirrors.desiredEnabled" : "mirrors.desiredDisabled")}</Table.Td>
        <Table.Td><MirrorEvent mirror={mirror} /></Table.Td>
        <Table.Td><MirrorNextAction mirror={mirror} /></Table.Td>
      </Table.Tr>)}
    </ListTable>
  </PageChrome>;
}
