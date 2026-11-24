"use client";

import { Badge, Button, Checkbox, Group, Select, Stack, Table, Text } from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import { useTranslate } from "@refinedev/core";
import { useCallback, useEffect, useRef, useState } from "react";
import { ListTable } from "@/components/display/ListTable";
import { ListToolbar } from "@/components/display/ListToolbar";
import { ForbiddenState } from "@/components/feedback/ForbiddenState";
import { HeaderActions } from "@/components/layout/HeaderActions";
import { PageChrome } from "@/components/layout/PageChrome";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { useConsoleLocation } from "@/components/navigation/useConsoleNavigation";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { useListQuery } from "@/hooks/useListQuery";
import type { PageQuery } from "@/lib/pagination";
import { listMirrorInventory } from "./api";
import { ATTENTION_CAUSES, FLEET_STATES, type AttentionCause, type InventoryMirror } from "./fleetTypes";
import { decimalBytes, utcSample } from "./fleetFormat";
import { OperationsNavigation, operationsScope } from "./OperationsNavigation";
import { mirrorDetailHref, rememberMirrorPosition, restoreMirrorPosition } from "./mirrorNavigation";
import classes from "./Operations.module.css";

const filters = [
  { key: "grouped_state", type: "select", defaultValue: "", accept: ["", ...FLEET_STATES] },
  { key: "published_only", type: "select", defaultValue: "", accept: ["", "1"] },
  { key: "cause", type: "select", defaultValue: "", accept: ["", ...ATTENTION_CAUSES] },
  { key: "sort", type: "select", defaultValue: "priority", accept: ["priority", "size", "rows", "table"] },
] as const;

export function MirrorInventory() {
  const t = useTranslate();
  const compact = useMediaQuery("(max-width: 48em)");
  const { href, search } = useConsoleLocation();
  const scope = operationsScope(search);
  const query = useListQuery({ filters });
  const state = query.select("grouped_state"), published = query.select("published_only") === "1";
  const cause = query.select("cause"), sort = query.select("sort"), q = query.search;
  const key = JSON.stringify({ ...scope, state, published, cause, sort, q });
  const activeKey = useRef(key);
  activeKey.current = key;
  const [causes, setCauses] = useState<Partial<Record<AttentionCause, number>>>({});
  useEffect(() => { if (state !== "attention" && cause) query.setFilter("cause", ""); }, [state, cause, query.setFilter]);
  const fetch = useCallback(async (page: PageQuery) => {
    const result = await listMirrorInventory({ ...page, ...scope, grouped_state: state, published_only: published, cause, sort, q });
    if (activeKey.current === key) setCauses(result.cause_counts);
    return result;
  }, [scope.source_id, scope.runtime_id, state, published, cause, sort, q, key]);
  const list = useConsolePagedList({ fetch, pageSize: 12, page: query.page, onPageChange: query.setPage, filtered: query.isFiltered });
  useEffect(() => { if (!list.loading) restoreMirrorPosition(href); }, [href, list.loading]);
  if (list.accessDenied) return <ForbiddenState reason="mirror:read" />;
  const attention = state === "attention";
  const controls = <Stack gap="sm"><ListToolbar query={query} searchPlaceholder={t("fleet.searchMirrors")}
      filters={[{ key: "grouped_state", label: t("fleet.stateFilter"), options: FLEET_STATES.map(value => ({ value, label: t(`fleet.state.${value}`) })) }]}
      extra={<><Checkbox label={t("fleet.publishedOnly")} checked={published} onChange={event => query.setFilter("published_only", event.currentTarget.checked ? "1" : "")} />
        <Select aria-label={t("fleet.sort")} value={sort} onChange={value => query.setFilter("sort", value ?? "priority")}
          data={["priority", "size", "rows", "table"].map(value => ({ value, label: t(`fleet.sort.${value}`) }))} /></>} />
      {attention && <Group gap="xs" role="group" aria-label={t("fleet.causeFilter")}>
        <Button size="xs" variant={!cause ? "light" : "subtle"} aria-pressed={!cause} onClick={() => query.setFilter("cause", "")}>{t("fleet.allCauses")}</Button>
        {ATTENTION_CAUSES.filter(value => (causes[value] ?? 0) > 0 || cause === value).map(value => <Button key={value} size="xs" variant={cause === value ? "light" : "subtle"} aria-pressed={cause === value} onClick={() => query.setFilter("cause", cause === value ? "" : value)}>{t(`fleet.cause.${value}`)} · {causes[value] ?? 0}</Button>)}
      </Group>}
      {attention && sort === "priority" && <Text size="xs" c="dimmed">{t("fleet.triageOrder")}</Text>}
    </Stack>;
  return <PageChrome title={t("fleet.inventory")} description={t("fleet.inventoryHelp")} fill={!compact}
    tabs={<OperationsNavigation view="inventory" scope={scope} />}
    actions={<HeaderActions navigation={<Button size="sm" variant="light" onClick={() => void list.reload()}>{t("common.refresh")}</Button>} />}
    toolbar={compact ? undefined : controls}>
    {compact && controls}
    <div className={classes.inventory}>
      <ListTable embedded={compact} list={list} columnCount={6} minWidth={0} emptyMessage={t("fleet.empty")} onClearFilters={query.clear}
        head={<Table.Tr>{["table", "source", "phase", "size", attention ? "reason" : "rows", "publication"].map(column => <Table.Th key={column}>{t(`fleet.column.${column}`)}</Table.Th>)}</Table.Tr>}>
        {list.items.map(mirror => <InventoryRow key={mirror.id} mirror={mirror} attention={attention} origin={href} />)}
      </ListTable>
    </div>
  </PageChrome>;
}

export function InventoryRow({ mirror, attention, origin }: { mirror: InventoryMirror; attention: boolean; origin: string }) {
  const t = useTranslate();
  const published = mirror.published_generation_id != null;
  return <Table.Tr>
    <Table.Td data-column="table"><ConsoleLink href={mirrorDetailHref(mirror.id, origin)} data-mirror-return={mirror.id}
      onClick={event => rememberMirrorPosition(origin, event.currentTarget)}>{mirror.qualified_table}</ConsoleLink><Text size="xs" c="dimmed">{mirror.id}</Text></Table.Td>
    <Table.Td data-column="source" data-label={t("fleet.column.source")}>{mirror.source_name || mirror.source_key || mirror.source_id}</Table.Td>
    <Table.Td data-column="phase"><Badge className={classes.stateBadge} variant="light" color={{ synchronizing: "green", copying: "blue", attention: "orange", stopped: "gray" }[mirror.grouped_state]}>{t(`fleet.state.${mirror.grouped_state}`)}</Badge><Text size="xs" mt={4}>{t(`mirrors.status.${mirror.status}`)}</Text></Table.Td>
    <Table.Td data-column="size" data-label={t("fleet.column.size")}>{decimalBytes(mirror.source_size_bytes)}</Table.Td>
    <Table.Td data-column={attention ? "reason" : "rows"} data-label={t(`fleet.column.${attention ? "reason" : "rows"}`)}>
      {attention ? <><Text size="sm">{mirror.attention_cause ? t(`fleet.cause.${mirror.attention_cause}`) : t("diagnostics.unavailable")}</Text>
        {mirror.attention_since && <Text size="xs" c="dimmed">{t("fleet.blockedSince")}: <time dateTime={mirror.attention_since}>{utcSample(mirror.attention_since)}</time></Text>}</>
        : mirror.estimated_rows?.toLocaleString() ?? t("diagnostics.unavailable")}
    </Table.Td>
    <Table.Td data-column="publication"><Text size="sm" fw={500}>{t(published ? "fleet.publishedCopy" : "fleet.unpublished")}</Text>
      {published && !mirror.enabled && <Text size="xs" c="dimmed">{t("fleet.retainedCopy")}</Text>}</Table.Td>
  </Table.Tr>;
}
