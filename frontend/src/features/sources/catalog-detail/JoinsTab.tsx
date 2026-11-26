"use client";

import { Badge, Button, Group, SegmentedControl, Select, Stack, Table, Text, TextInput } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useCallback, useLayoutEffect, useRef, useState } from "react";
import { ListTable } from "@/components/display/ListTable";
import { FillColumn } from "@/components/layout/FillColumn";
import { SectionHeader } from "@/components/layout/SectionHeader";
import { listObjectJoins } from "@/features/sources/api/joins";
import type { CatalogJoin, CatalogObject } from "@/features/sources/types";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import type { PageQuery } from "@/lib/pagination";
import { RelationActions } from "./RelationActions";
import { RelationPaths } from "./RelationPaths";
import { RelationSummary, relationName } from "./RelationSummary";
import { RelationBuilder } from "./RelationBuilder";
import { RelationGraph } from "./RelationGraph";
import styles from "./RelationGraph.module.css";

type JoinsTabProps = { object: CatalogObject; writable: boolean; listEnabled?: boolean };
type Workspace = { kind: "browse" | "new" | "paths" } | { kind: "relation"; id: string; mode: "view" | "edit" };

export function JoinsTab(props: JoinsTabProps) {
  return <JoinsWorkspace key={props.object.id} {...props} />;
}

function JoinsWorkspace({ object, writable, listEnabled = true }: JoinsTabProps) {
  const t = useTranslate();
  const [view, setView] = useState("graph");
  const [workspace, setWorkspace] = useState<Workspace>({ kind: "browse" });
  const [search, setSearch] = useState("");
  const [column, setColumn] = useState<string | null>(null);
  const [directionFilter, setDirectionFilter] = useState<string>("all");
  const [stateFilter, setStateFilter] = useState<string>("all");
  const [originFilter, setOriginFilter] = useState<string>("all");
  const [selected, setSelected] = useState<string | null>(null);
  const searchRef = useRef<HTMLInputElement>(null);
  const returnTarget = useRef<HTMLElement | SVGElement | null>(null);
  const [restoreFocus, setRestoreFocus] = useState(false);
  const loadedPages = useRef(new WeakMap<CatalogJoin[], number>());
  const fetchPage = useCallback(async (query: PageQuery) => {
    const result = await listObjectJoins(object.id, query);
    loadedPages.current.set(result.items, Math.floor(result.offset / result.limit) + 1);
    return result;
  }, [object.id]);
  const list = useConsolePagedList({ pageSize: 50, fetch: fetchPage, resetDeps: [object.id], enabled: listEnabled });
  const { items: joins, reload } = list;
  const relation = workspace.kind === "relation" ? joins.find((join) => join.id === workspace.id) : undefined;
  const neighborhoodLoaded = listEnabled && list.presentation.state !== "unloaded" && list.presentation.state !== "loading";
  const hasActiveFilter = Boolean(
    search ||
      column ||
      directionFilter !== "all" ||
      stateFilter !== "all" ||
      originFilter !== "all",
  );
  const clearFilters = () => {
    setSearch("");
    setColumn(null);
    setDirectionFilter("all");
    setStateFilter("all");
    setOriginFilter("all");
  };
  const visibleJoins = joins.filter((join) => {
    if (
      !`${relationName(object, join)} ${join.evidence} ${join.join_kind ?? "INNER"}`
        .toLowerCase()
        .includes(search.toLowerCase())
    ) {
      return false;
    }
    if (column && join.from_column_id !== column && join.to_column_id !== column) {
      return false;
    }
    if (directionFilter !== "all") {
      const fromLocal = object.columns.some((item) => item.id === join.from_column_id);
      const toLocal = object.columns.some((item) => item.id === join.to_column_id);
      const joinDirection = fromLocal ? (toLocal ? "same" : "outgoing") : "incoming";
      if (joinDirection !== directionFilter) return false;
    }
    if (stateFilter === "asserted" && join.is_rejected) return false;
    if (stateFilter === "rejected" && !join.is_rejected) return false;
    if (originFilter === "manual" && !join.created_by_user_id) return false;
    if (originFilter === "automated" && join.created_by_user_id) return false;
    return true;
  });
  const openRelation = (join: CatalogJoin, mode: "view" | "edit", target: HTMLElement | SVGElement) => {
    returnTarget.current = target;
    setSelected(join.id);
    setWorkspace({ kind: "relation", id: join.id, mode });
  };
  const exitRelation = () => { setWorkspace({ kind: "browse" }); setRestoreFocus(true); };
  useLayoutEffect(() => {
    if (list.loading) return;
    if (selected && !joins.some((join) => join.id === selected)) setSelected(null);
    if (workspace.kind === "relation") {
      if (!relation) {
        returnTarget.current = null;
        setWorkspace({ kind: "browse" });
        setRestoreFocus(true);
      } else if (workspace.mode === "edit" && (!writable || relation.is_rejected)) {
        setWorkspace({ kind: "relation", id: relation.id, mode: "view" });
      }
    }
  }, [joins, list.loading, selected, workspace, relation, writable]);
  useLayoutEffect(() => {
    if (!restoreFocus || list.loading || workspace.kind !== "browse") return;
    const target = returnTarget.current;
    if (target?.isConnected && target.getClientRects().length && !target.closest("[hidden]")) target.focus();
    if (!target || document.activeElement !== target) searchRef.current?.focus();
    returnTarget.current = null;
    setRestoreFocus(false);
  }, [restoreFocus, list.loading, workspace, joins]);

  const exploreRef = useRef<HTMLButtonElement>(null);
  const exitPaths = () => { setWorkspace({ kind: "browse" }); requestAnimationFrame(() => exploreRef.current?.focus()); };
  const addRef = useRef<HTMLButtonElement>(null);
  const addAction = writable && (workspace.kind === "browse" || workspace.kind === "paths") ? (
    <Button ref={addRef} size="sm" onClick={() => setWorkspace({ kind: "new" })}>
      {t("catalog.joins.add")}
    </Button>
  ) : null;

  return (
    <div className={styles.frame} data-authoring={workspace.kind === "new" || workspace.kind === "relation"}><FillColumn gap="sm">
      <div style={{ flexShrink: 0 }}>
        <SectionHeader
          title={t("catalog.joins.title")}
          order={4}
          actions={
            <Group gap="xs" align="flex-end">
              {workspace.kind === "browse" ? <Button ref={exploreRef} size="sm" variant="default" onClick={() => setWorkspace({ kind: "paths" })}>
                {t("catalog.joins.path.explore")}
              </Button> : null}
              {addAction}
            </Group>
          }
        />
      </div>
      {workspace.kind === "paths" ? <RelationPaths object={object} joins={joins} onClose={exitPaths} /> : null}
      {workspace.kind === "browse" || workspace.kind === "relation" ? <div className={styles.browse} hidden={workspace.kind === "relation"}>
      <Text size="xs" c="dimmed">{t("catalog.joins.graph.legend")}</Text>
      {neighborhoodLoaded ? <Text size="xs" c="dimmed" aria-live="polite">{t("catalog.joins.graph.coverage", { loaded: joins.length, total: list.total, page: loadedPages.current.get(joins) })}</Text> : null}
      <div className={styles.viewSwitch}><SegmentedControl size="xs" value={view} onChange={setView} data={[{ value: "graph", label: t("catalog.joins.graph.title") }, { value: "index", label: t("catalog.joins.graph.index") }]} /></div>
      <div className={styles.workspace} data-view={view} data-unloaded={!neighborhoodLoaded || undefined}>
      {neighborhoodLoaded ? <RelationGraph key={object.id} object={object} joins={joins} selected={selected} onSelect={(join, target) => openRelation(join, "view", target)} column={column} onColumn={setColumn} /> : null}
      <section className={styles.index} aria-label={t("catalog.joins.graph.index")}>
      <TextInput ref={searchRef} size="xs" aria-label={t("catalog.joins.graph.search")} placeholder={t("catalog.joins.graph.search")} value={search} onChange={(event) => setSearch(event.currentTarget.value)} />
      <Group gap="xs" wrap="wrap">
        <Select
          size="xs"
          aria-label={t("catalog.joins.filterDirection")}
          value={directionFilter}
          onChange={(value) => setDirectionFilter(value ?? "all")}
          allowDeselect={false}
          data={[
            { value: "all", label: `${t("catalog.joins.filterDirection")}: ${t("catalog.joins.filterAll")}` },
            { value: "outgoing", label: `${t("catalog.joins.filterDirection")}: ${t("catalog.joins.outgoing")}` },
            { value: "incoming", label: `${t("catalog.joins.filterDirection")}: ${t("catalog.joins.incoming")}` },
            { value: "same", label: `${t("catalog.joins.filterDirection")}: ${t("catalog.joins.sameObject")}` },
          ]}
          miw={130}
          style={{ flex: "1 1 130px" }}
        />
        <Select
          size="xs"
          aria-label={t("catalog.joins.filterStatus")}
          value={stateFilter}
          onChange={(value) => setStateFilter(value ?? "all")}
          allowDeselect={false}
          data={[
            { value: "all", label: `${t("catalog.joins.filterStatus")}: ${t("catalog.joins.filterAll")}` },
            { value: "asserted", label: `${t("catalog.joins.filterStatus")}: ${t("catalog.joins.filterAsserted")}` },
            { value: "rejected", label: `${t("catalog.joins.filterStatus")}: ${t("catalog.joins.state.rejected")}` },
          ]}
          miw={115}
          style={{ flex: "1 1 115px" }}
        />
        <Select
          size="xs"
          aria-label={t("catalog.joins.filterProvenance")}
          value={originFilter}
          onChange={(value) => setOriginFilter(value ?? "all")}
          allowDeselect={false}
          data={[
            { value: "all", label: `${t("catalog.joins.filterProvenance")}: ${t("catalog.joins.filterAll")}` },
            { value: "manual", label: `${t("catalog.joins.filterProvenance")}: ${t("catalog.joins.state.manual")}` },
            { value: "automated", label: `${t("catalog.joins.filterProvenance")}: ${t("catalog.joins.state.automated")}` },
          ]}
          miw={120}
          style={{ flex: "1 1 120px" }}
        />
      </Group>
      <ListTable
        list={list.presentation.state === "ready" && visibleJoins.length === 0 ? { ...list, presentation: { ...list.presentation, state: "no-match" } } : list}
        columnCount={1}
        minWidth={0}
        emptyMessage={t("catalog.joins.empty")}
        emptyAction={addAction}
        onClearFilters={hasActiveFilter ? clearFilters : undefined}
        head={<Table.Tr><Table.Th>{t("catalog.joins.graph.index")}</Table.Th></Table.Tr>}
      >
        {visibleJoins.map((join) => (
          <Table.Tr key={join.id} aria-selected={selected === join.id}>
            <Table.Td>
              <RelationSummary object={object} join={join} compact />
              <Text size="xs">{join.join_kind ?? "INNER"} · <span>{t(object.columns.some((item) => item.id === join.from_column_id) ? (object.columns.some((item) => item.id === join.to_column_id) ? "catalog.joins.sameObject" : "catalog.joins.outgoing") : "catalog.joins.incoming")}</span></Text>
              <Stack gap={4}>
                {join.is_rejected ? <Badge size="xs" color="red">{t("catalog.joins.state.rejected")}</Badge> : null}
                <Text size="xs" c="dimmed">{t(join.created_by_user_id ? "catalog.joins.state.manual" : "catalog.joins.state.automated")}</Text>
              </Stack>
              <RelationActions object={object} join={join} writable={writable} onInspect={(target) => openRelation(join, "view", target)} onAmend={(target) => openRelation(join, "edit", target)} onChanged={reload} />
            </Table.Td>
          </Table.Tr>
        ))}
      </ListTable>
      </section>
      </div>
      </div> : null}
      {workspace.kind === "relation" && relation ? <RelationBuilder
        key={`${object.id}:${relation.id}:${workspace.mode}`}
        object={object}
        join={relation}
        mode={workspace.mode}
        writable={writable}
        onAmend={() => setWorkspace({ kind: "relation", id: relation.id, mode: "edit" })}
        onChanged={reload}
        onClose={() => workspace.mode === "edit" ? setWorkspace({ kind: "relation", id: relation.id, mode: "view" }) : exitRelation()}
        onSaved={async () => {
          await reload();
          setWorkspace((current) => current.kind === "relation" && current.id === relation.id ? { ...current, mode: "view" } : current);
        }}
      /> : null}
      {writable && workspace.kind === "new" ? <RelationBuilder
        key={`${object.id}:new`}
        object={object}
        localColumn={object.columns.find((item) => item.id === column && item.is_present)?.id}
        onClose={() => { setWorkspace({ kind: "browse" }); requestAnimationFrame(() => addRef.current?.focus()); }}
        onSaved={async () => {
          setWorkspace({ kind: "browse" });
          await reload();
          addRef.current?.focus();
        }}
      /> : null}
    </FillColumn></div>
  );
}
