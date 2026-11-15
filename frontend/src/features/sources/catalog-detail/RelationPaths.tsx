"use client";

import { Button, Group, Stack, Text, UnstyledButton } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useRef, useState } from "react";
import { StatusBadge } from "@/components/display/StatusBadge";
import { NumberField } from "@/components/form/NumberField";
import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { getJoinPath } from "@/features/sources/api/joins";
import type { CatalogJoin, CatalogObject, JoinPathResult } from "@/features/sources/types";
import { RelationGraph } from "./RelationGraph";
import styles from "./RelationGraph.module.css";

type PathState = { status: "loading" } | { status: "unloaded"; hops: number } | { status: "ready"; result: JoinPathResult; hops: number };

export function RelationPaths({ object, joins, onClose }: { object: CatalogObject; joins: CatalogJoin[]; onClose: () => void }) {
  const t = useTranslate();
  const [maxHops, setMaxHops] = useState<number | string>(2);
  const [state, setState] = useState<PathState>({ status: "loading" });
  const [selected, setSelected] = useState(0);
  const [view, setView] = useState("graph");
  const boundsRef = useRef<HTMLInputElement>(null);
  const generation = useRef(0);
  const active = useRef(false);
  const inFlight = useRef(false);
  async function load(hops: number) {
    if (!active.current || inFlight.current) return;
    const request = ++generation.current;
    inFlight.current = true;
    setState({ status: "loading" });
    setSelected(0);
    try {
      const result = await getJoinPath({ start: object.id, max_hops: hops, top_targets: 10 });
      if (active.current && request === generation.current) setState({ status: "ready", result, hops });
    } catch (error) {
      if (!active.current || request !== generation.current) return;
      setState({ status: "unloaded", hops });
      presentProblemNotification(t, error, { onRetry: () => { if (active.current && request === generation.current) void load(hops); } });
    } finally { if (request === generation.current) inFlight.current = false; }
  }
  useEffect(() => {
    active.current = true;
    boundsRef.current?.focus();
    void load(2);
    return () => { active.current = false; generation.current += 1; inFlight.current = false; };
  }, [object.id]);
  const valid = typeof maxHops === "number" && Number.isInteger(maxHops) && maxHops >= 1 && maxHops <= 5;
  const route = state.status === "ready" ? state.result.paths[selected] : undefined;
  return <section aria-label={t("catalog.joins.path.title")} className={styles.paths}>
    <form onSubmit={(event) => { event.preventDefault(); if (typeof maxHops === "number" && valid) void load(maxHops); }}>
      <Group gap="sm" align="flex-end">
        <NumberField ref={boundsRef} editable label={t("catalog.joins.path.maxHops")} value={maxHops} onChange={setMaxHops} min={1} max={5} allowDecimal={false} w={140} />
        <Button type="submit" variant="light" loading={state.status === "loading"} disabled={!valid}>{t("catalog.joins.path.explore")}</Button>
        <Button variant="default" onClick={onClose}>{t("catalog.joins.path.exit")}</Button>
      </Group>
    </form>
    <Text size="xs" c="dimmed">{t("catalog.joins.path.scope")}</Text>
    {state.status === "loading" ? <Text role="status" size="sm">{t("catalog.joins.path.loading")}</Text> : state.status === "unloaded" ? <UnstyledButton aria-label={t("common.retry")} onClick={() => void load(state.hops)}><StatusBadge tone="danger" labelKey="status.unloaded" /></UnstyledButton> : <>
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
            {route.target_object_id ? <Button component={ConsoleLink} href={`/console/catalog/${encodeURIComponent(route.target_object_id)}`} size="xs" variant="light">{t("catalog.joins.path.openTarget")}</Button> : null}
          </section>
        </div>
      </> : <Text size="sm" c="dimmed">{t("catalog.joins.path.empty")}</Text>}
    </>}
  </section>;
}
