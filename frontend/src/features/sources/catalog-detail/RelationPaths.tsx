"use client";

import { Button, Code, Group, Select, Stack, Text, TextInput, UnstyledButton } from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import { useEffect, useMemo, useRef, useState } from "react";
import { StatusBadge } from "@/components/display/StatusBadge";
import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { NumberField } from "@/components/form/NumberField";
import { CopyIcon } from "@/components/icons";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { searchCatalogObjects } from "@/features/sources/api/catalog";
import { getJoinPath } from "@/features/sources/api/joins";
import type { CatalogJoin, CatalogObject, JoinPath, JoinPathResult } from "@/features/sources/types";
import { copyText } from "@/lib/copy-text";
import { RelationGraph } from "./RelationGraph";
import styles from "./RelationGraph.module.css";

type PathState = { status: "loading" } | { status: "unloaded"; hops: number } | { status: "ready"; result: JoinPathResult; hops: number };

type TargetOption = { value: string; label: string };

function columnEndpointInfo(object: CatalogObject, columnId: string, locator?: string | null) {
  const localCol = object.columns.find((col) => col.id === columnId);
  if (localCol) {
    const table = `${object.schema_name}.${object.name}`;
    return { table, qualifiedColumn: `${object.name}.${localCol.name}` };
  }
  if (locator) {
    const parts = locator.split("/");
    if (parts.length >= 8 && parts[3] && parts[5] && parts[7]) {
      return {
        table: `${parts[3]}.${parts[5]}`,
        qualifiedColumn: `${parts[5]}.${parts[7]}`,
      };
    }
  }
  return { table: null, qualifiedColumn: columnId };
}

export function buildJoinSqlSkeleton(object: CatalogObject, route: JoinPath): string {
  const startTable = `${object.schema_name}.${object.name}`;
  const joinedTables = new Set<string>([startTable]);
  const clauses: string[] = [`SELECT *`, `FROM ${startTable}`];

  for (const hop of route.hops) {
    const fromInfo = columnEndpointInfo(object, hop.from_column_id, hop.from_column_locator_key);
    const toInfo = columnEndpointInfo(object, hop.to_column_id, hop.to_column_locator_key);
    const joinKeyword = `${(hop.join_kind || "INNER").toUpperCase()} JOIN`;
    const condition =
      hop.join_expression?.trim() ||
      `${fromInfo.qualifiedColumn} = ${toInfo.qualifiedColumn}`;

    let nextTable = toInfo.table;
    if (!nextTable || joinedTables.has(nextTable)) {
      if (fromInfo.table && !joinedTables.has(fromInfo.table)) {
        nextTable = fromInfo.table;
      } else {
        nextTable = toInfo.table ?? fromInfo.table ?? "target_table";
      }
    }
    joinedTables.add(nextTable);
    clauses.push(`${joinKeyword} ${nextTable} ON ${condition}`);
  }

  return clauses.join("\n");
}

export function RelationPaths({ object, joins, onClose }: { object: CatalogObject; joins: CatalogJoin[]; onClose: () => void }) {
  const t = useTranslate();
  const { open } = useNotification();
  const [maxHops, setMaxHops] = useState<number | string>(2);
  const [targetObjectId, setTargetObjectId] = useState<string | null>(null);
  const [targetSearch, setTargetSearch] = useState("");
  const [targetOptions, setTargetOptions] = useState<TargetOption[]>([]);
  const [question, setQuestion] = useState("");
  const [state, setState] = useState<PathState>({ status: "loading" });
  const [selected, setSelected] = useState(0);
  const [view, setView] = useState("graph");
  const boundsRef = useRef<HTMLInputElement>(null);
  const generation = useRef(0);
  const active = useRef(false);
  const inFlight = useRef(false);
  const searchGeneration = useRef(0);
  const selectedOptionRef = useRef<TargetOption | null>(null);

  async function load(hops: number, target?: string | null, q?: string) {
    if (!active.current || inFlight.current) return;
    const request = ++generation.current;
    inFlight.current = true;
    setState({ status: "loading" });
    setSelected(0);
    try {
      const params: Parameters<typeof getJoinPath>[0] = {
        start: object.id,
        max_hops: hops,
        top_targets: 10,
      };
      if (target) params.target = target;
      const trimmedQuestion = q?.trim();
      if (trimmedQuestion) params.q = trimmedQuestion;
      const result = await getJoinPath(params);
      if (active.current && request === generation.current) setState({ status: "ready", result, hops });
    } catch (error) {
      if (!active.current || request !== generation.current) return;
      setState({ status: "unloaded", hops });
      presentProblemNotification(t, error, {
        onRetry: () => {
          if (active.current && request === generation.current) {
            void load(hops, target, q);
          }
        },
      });
    } finally {
      if (request === generation.current) inFlight.current = false;
    }
  }

  useEffect(() => {
    active.current = true;
    boundsRef.current?.focus();
    void load(2);
    return () => { active.current = false; generation.current += 1; inFlight.current = false; };
  }, [object.id]);

  useEffect(() => {
    const query = targetSearch.trim();
    if (!query) return;
    if (selectedOptionRef.current && query === selectedOptionRef.current.label) return;
    const req = ++searchGeneration.current;
    const timer = window.setTimeout(() => {
      void searchCatalogObjects(query, { source_id: object.source_id, limit: 20 })
        .then((res) => {
          if (req !== searchGeneration.current) return;
          const next = res.items.map((item) => ({
            value: item.id,
            label: `${item.schema_name}.${item.name} · ${item.locator_key}`,
          }));
          if (
            selectedOptionRef.current &&
            !next.some((item) => item.value === selectedOptionRef.current?.value)
          ) {
            next.unshift(selectedOptionRef.current);
          }
          setTargetOptions(next);
        })
        .catch(() => {
          // Keep existing options on transient search error
        });
    }, 250);
    return () => window.clearTimeout(timer);
  }, [targetSearch, object.source_id]);

  const valid = typeof maxHops === "number" && Number.isInteger(maxHops) && maxHops >= 1 && maxHops <= 5;
  const route = state.status === "ready" ? state.result.paths[selected] : undefined;
  const sqlSkeleton = useMemo(
    () => (route && route.hops.length > 0 ? buildJoinSqlSkeleton(object, route) : ""),
    [object, route],
  );

  const copySql = async () => {
    if (!sqlSkeleton) return;
    try {
      await copyText(sqlSkeleton);
      open?.({ type: "success", message: t("common.copy.success") });
    } catch {
      open?.({ type: "error", message: t("common.copy.failed") });
    }
  };

  return <section aria-label={t("catalog.joins.path.title")} className={styles.paths}>
    <form onSubmit={(event) => { event.preventDefault(); if (typeof maxHops === "number" && valid) void load(maxHops, targetObjectId, question); }}>
      <Group gap="sm" align="flex-end" wrap="wrap">
        <NumberField ref={boundsRef} editable label={t("catalog.joins.path.maxHops")} value={maxHops} onChange={setMaxHops} min={1} max={5} allowDecimal={false} w={140} />
        <Select
          label={t("catalog.joins.path.targetObject")}
          placeholder={t("catalog.joins.path.targetPlaceholder")}
          data={targetOptions}
          value={targetObjectId}
          searchValue={targetSearch}
          onChange={(value) => {
            setTargetObjectId(value);
            const opt = value ? targetOptions.find((item) => item.value === value) ?? null : null;
            selectedOptionRef.current = opt;
            setTargetSearch(opt ? opt.label : "");
          }}
          onSearchChange={setTargetSearch}
          filter={({ options }) => options}
          searchable
          clearable
          miw={220}
          style={{ flex: "1 1 220px" }}
        />
        <TextInput
          label={t("catalog.joins.path.question")}
          placeholder={t("catalog.joins.path.questionPlaceholder")}
          value={question}
          onChange={(event) => setQuestion(event.currentTarget.value)}
          miw={220}
          style={{ flex: "1 1 220px" }}
        />
        <Button type="submit" variant="light" loading={state.status === "loading"} disabled={!valid}>{t("catalog.joins.path.explore")}</Button>
        <Button variant="default" onClick={onClose}>{t("catalog.joins.path.exit")}</Button>
      </Group>
    </form>
    <Text size="xs" c="dimmed">{t("catalog.joins.path.scope")}</Text>
    {state.status === "loading" ? <Text role="status" size="sm">{t("catalog.joins.path.loading")}</Text> : state.status === "unloaded" ? <UnstyledButton aria-label={t("common.retry")} onClick={() => void load(state.hops, targetObjectId, question)}><StatusBadge tone="danger" labelKey="status.unloaded" /></UnstyledButton> : <>
      <Text size="xs" aria-live="polite">{t("catalog.joins.path.coverage", { count: state.result.paths.length, hops: state.hops })}</Text>
      {route ? <>
        <Group className={styles.routeSwitch}><Button size="xs" aria-pressed={view === "graph"} variant={view === "graph" ? "light" : "default"} onClick={() => setView("graph")}>{t("catalog.joins.graph.title")}</Button><Button size="xs" aria-pressed={view === "index"} variant={view === "index" ? "light" : "default"} onClick={() => setView("index")}>{t("catalog.joins.path.title")}</Button></Group>
        <div className={styles.workspace} data-view={view}>
          <RelationGraph key={`route:${selected}`} object={object} joins={joins} route={route} selected={null} onSelect={() => {}} column={null} onColumn={() => {}} />
          <section className={`${styles.index} ${styles.routeIndex}`} aria-label={t("catalog.joins.path.routes")}>
            {state.result.paths.map((path, index) => <Button key={index} variant={index === selected ? "light" : "default"} aria-pressed={index === selected} size="xs" onClick={() => setSelected(index)} styles={{ label: { whiteSpace: "normal", overflowWrap: "anywhere" } }} h="auto" mih={36}>{index + 1}. {t("catalog.joins.path.summary")}: {path.path_summary}</Button>)}
            <Text size="xs">{t("catalog.joins.path.traversalDirection")}</Text>
            {route.hops.map((hop, index) => <Stack key={`${hop.join_id}:${index}`} gap={4} className={styles.hop}>
              <Text size="sm" fw={600}>{t("catalog.joins.path.hop", { number: index + 1 })}: {hop.from_column_locator_key ?? hop.from_column_id} → {hop.to_column_locator_key ?? hop.to_column_id}</Text>
              <Text size="xs">{t("catalog.joins.path.reportedKind")}: {hop.join_kind}</Text>
              <Text size="xs">{t("catalog.joins.expression")}: {hop.join_expression ?? "—"}</Text>
              <Text size="xs">{t("catalog.joins.evidence")}: {hop.evidence}</Text>
            </Stack>)}
            {sqlSkeleton ? (
              <Stack gap={4} className={styles.hop}>
                <Group justify="space-between" align="center" gap="xs">
                  <Text size="xs" fw={600}>{t("catalog.joins.path.sqlPreview")}</Text>
                  <Button
                    size="compact-xs"
                    variant="light"
                    leftSection={<CopyIcon size={12} aria-hidden />}
                    onClick={() => void copySql()}
                  >
                    {t("catalog.joins.path.copySql")}
                  </Button>
                </Group>
                <Code block style={{ whiteSpace: "pre-wrap", fontSize: "var(--mantine-font-size-xs)" }}>
                  {sqlSkeleton}
                </Code>
              </Stack>
            ) : null}
            {route.target_object_id ? <Button component={ConsoleLink} href={`/console/catalog/${encodeURIComponent(route.target_object_id)}`} size="xs" variant="light">{t("catalog.joins.path.openTarget")}</Button> : null}
          </section>
        </div>
      </> : <Text size="sm" c="dimmed">{t("catalog.joins.path.empty")}</Text>}
    </>}
  </section>;
}
