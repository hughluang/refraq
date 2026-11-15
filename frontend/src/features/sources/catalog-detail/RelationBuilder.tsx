"use client";

import { Badge, Button, Group, Stack, Text } from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { confirmLeave, releaseLeaveGuardSuppression } from "@/components/navigation/leaveGuard";
import styles from "./RelationBuilder.module.css";
import { FormSection } from "@/components/form/FormSection";
import { SelectField } from "@/components/form/SelectField";
import { TextareaField } from "@/components/form/TextareaField";
import { useConsoleForm } from "@/components/form/useConsoleForm";
import { presentSaveFailure } from "@/components/feedback/presentSaveFailure";
import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { getCatalogObject, searchCatalogObjects } from "@/features/sources/api/catalog";
import { createJoin, patchJoin } from "@/features/sources/api/joins";
import type { CatalogJoin, CatalogObject } from "@/features/sources/types";
import { useSearchDebounce } from "@/hooks/useSearchDebounce";
import { mergeSelectedOption, type JoinSelectOption } from "./joinEdges";
import { problemMessage } from "@/lib/problem";
import { RelationSummary } from "./RelationSummary";
import { RelationActions } from "./RelationActions";
import { DisplayField } from "@/components/display/DisplayField";
import { Instant } from "@/components/display/Instant";

type Values = { direction: string; local: string | null; remoteObject: string | null; remote: string | null; kind: string; expression: string; evidence: string };
type Props = { object: CatalogObject; join?: CatalogJoin; mode?: "view" | "edit"; writable?: boolean; localColumn?: string; onClose: () => void; onSaved: () => Promise<void>; onAmend?: () => void; onChanged?: () => Promise<void> };

export function RelationBuilder({ object, join, mode = "edit", writable = true, localColumn, onClose, onSaved, onAmend, onChanged }: Props) {
  const editable = !join || mode === "edit";
  const t = useTranslate();
  const { open } = useNotification();
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const form = useConsoleForm<Values>({
    initialValues: { direction: "outgoing", local: localColumn ?? null, remoteObject: null, remote: null, kind: join?.join_kind ?? "INNER", expression: join?.join_expression ?? "", evidence: join?.evidence ?? "" },
    validate: {
      local: (value) => !join && !value ? t("catalog.joins.columnRequired") : null,
      remoteObject: (value) => !join && !value ? t("catalog.joins.objectRequired") : null,
      remote: (value, values) => join ? null : !value ? t("catalog.joins.columnRequired") : value === values.local ? t("catalog.joins.distinctColumns") : null,
      evidence: (value) => value.trim() ? null : t("catalog.joins.evidenceRequired"),
    },
  });
  const [saveProblem, setSaveProblem] = useState<string | null>(null);
  useLayoutEffect(() => {
    if (join && !editable) {
      const values = { direction: "outgoing", local: null, remoteObject: null, remote: null, kind: join.join_kind ?? "INNER", expression: join.join_expression ?? "", evidence: join.evidence };
      form.setValues(values);
      form.resetDirty(values);
      form.clearErrors();
      setSaveProblem(null);
    }
    // Saved detail tracks refreshed records; an active edit keeps its draft.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [join, editable]);
  const [search, setSearch] = useState("");
  const currentOption = { value: object.id, label: `${object.schema_name}.${object.name} · ${object.locator_key}` };
  const [objects, setObjects] = useState<JoinSelectOption[]>([currentOption]);
  const [searchLoading, setSearchLoading] = useState(false);
  const [truncated, setTruncated] = useState(false);
  const [searchFailed, setSearchFailed] = useState(false);
  const [searchRetry, setSearchRetry] = useState(0);
  const [remoteObject, setRemoteObject] = useState<CatalogObject | null>(null);
  const [columnLoading, setColumnLoading] = useState(false);
  const [columnFailed, setColumnFailed] = useState(false);
  const [columnRetry, setColumnRetry] = useState(0);
  const selected = form.values.remoteObject;
  const selectedRef = useRef(selected);
  selectedRef.current = selected;
  const selectedLabel = objects.find((option) => option.value === selected)?.label ?? "";
  const searchTerm = search === selectedLabel ? "" : search;
  const query = useSearchDebounce(searchTerm).trim();
  const searchRef = useRef(searchTerm);
  searchRef.current = searchTerm;
  useEffect(() => {
    if (join || searchRef.current.trim() !== query) return;
    let cancelled = false;
    setSearchFailed(false);
    setTruncated(false);
    if (!query) { setObjects((previous) => mergeSelectedOption([currentOption], selected, previous)); setSearchLoading(false); return; }
    setSearchLoading(true);
    void searchCatalogObjects(query, { limit: 20 }).then((result) => {
      if (cancelled || searchRef.current.trim() !== query) return;
      const options = result.items.filter((item) => item.is_present && item.id !== object.id).map((item) => ({ value: item.id, label: `${item.schema_name}.${item.name} · ${item.locator_key}` }));
      setObjects((previous) => mergeSelectedOption([currentOption, ...options], selectedRef.current, previous));
      setTruncated(result.truncated);
    }).catch((error) => {
      if (cancelled || searchRef.current.trim() !== query) return;
      setObjects((previous) => mergeSelectedOption([currentOption], selectedRef.current, previous));
      setSearchFailed(true);
      presentProblemNotification(t, error, { onRetry: () => {
        if (!cancelled && searchRef.current.trim() === query) setSearchRetry((value) => value + 1);
      } });
    }).finally(() => { if (!cancelled) setSearchLoading(false); });
    return () => { cancelled = true; };
    // Selection retention does not restart a ranked search.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, searchRetry, object.id, join]);
  useEffect(() => {
    if (join) return;
    let cancelled = false;
    setRemoteObject(null);
    setColumnFailed(false);
    setColumnLoading(false);
    if (!selected) return;
    if (selected === object.id) { setRemoteObject(object); return; }
    setColumnLoading(true);
    void getCatalogObject(selected).then((result) => {
      if (!cancelled && selectedRef.current === selected) setRemoteObject(result.object);
    }).catch((error) => {
      if (cancelled || selectedRef.current !== selected) return;
      setColumnFailed(true);
      presentProblemNotification(t, error, { onRetry: () => {
        if (!cancelled && selectedRef.current === selected) setColumnRetry((value) => value + 1);
      } });
    }).finally(() => { if (!cancelled) setColumnLoading(false); });
    return () => { cancelled = true; };
  }, [selected, object, join, columnRetry]);
  const columns = (target: CatalogObject | null) => target?.columns.filter((column) => column.is_present).map((column) => ({ value: column.id, label: `${column.name} · ${column.data_type}` })) ?? [];
  const remoteReady = remoteObject?.id === selected && !columnLoading;
  const save = () => form.submit(async (values) => {
    setSaveProblem(null);
    try {
      const details = { evidence: values.evidence.trim(), join_kind: values.kind, join_expression: join && values.expression === (join.join_expression ?? "") ? join.join_expression ?? null : values.expression };
      if (join) await patchJoin(join.id, details);
      else {
        const incoming = values.direction === "incoming";
        await createJoin({ ...details, join_expression: values.expression || null, from_column_id: (incoming ? values.remote : values.local)!, to_column_id: (incoming ? values.local : values.remote)! });
      }
    } catch (error) {
      if (alive.current) {
        presentSaveFailure(t, error, (failure) => {
          const result = form.applyApiError(failure, { ...(!join ? { from_column_id: values.direction === "incoming" ? "remote" : "local", to_column_id: values.direction === "incoming" ? "local" : "remote" } : {}), join_kind: "kind", join_expression: "expression" });
          if (!result.mapped.length || result.unmapped.length) setSaveProblem(problemMessage(t, error, t("problems.unknown")));
          return result;
        });
      }
      throw error;
    }
    if (!alive.current) return;
    form.markSaved();
    open?.({ type: "success", message: t("catalog.joins.saved") });
    await onSaved();
  });
  const requestClose = async () => {
    if (form.submitting) return;
    if (form.dirty && !await confirmLeave()) return;
    releaseLeaveGuardSuppression();
    onClose();
  };
  const root = useRef<HTMLFormElement>(null);
  useEffect(() => {
    if (editable) root.current?.querySelector<HTMLElement>("input:not([type=hidden]), textarea")?.focus();
    else root.current?.querySelector<HTMLButtonElement>("button")?.focus();
  }, [editable]);
  const incoming = form.values.direction === "incoming";
  const localName = object.columns.find((item) => item.id === form.values.local)?.name ?? "…";
  const remoteName = remoteObject?.columns.find((item) => item.id === form.values.remote)?.name ?? "…";
  const localEndpoint = `${object.name}.${localName}`;
  const remoteEndpoint = `${remoteObject?.name ?? "…"}.${remoteName}`;
  const preview = useRef<HTMLDivElement>(null);
  const localPort = useRef<HTMLParagraphElement>(null);
  const remotePort = useRef<HTMLParagraphElement>(null);
  const markerId = useId();
  const [connector, setConnector] = useState<string | null>(null);
  useLayoutEffect(() => {
    if (join) return;
    const measure = () => {
      if (!preview.current || !localPort.current || !remotePort.current || !form.values.local || !form.values.remote) { setConnector(null); return; }
      const frame = preview.current.getBoundingClientRect();
      const local = localPort.current.getBoundingClientRect();
      const remote = remotePort.current.getBoundingClientRect();
      const stacked = remote.top > local.bottom && remote.left < local.right;
      const a = { x: local.right - frame.left, y: local.top + local.height / 2 - frame.top };
      const b = { x: (stacked ? remote.right : remote.left) - frame.left, y: remote.top + remote.height / 2 - frame.top };
      const from = incoming ? b : a;
      const to = incoming ? a : b;
      const bend = stacked ? frame.width - 10 : (a.x + b.x) / 2;
      setConnector(`M ${from.x} ${from.y} C ${bend} ${from.y}, ${bend} ${to.y}, ${to.x} ${to.y}`);
    };
    measure();
    const observer = new ResizeObserver(measure);
    for (const node of [preview.current, localPort.current, remotePort.current, localPort.current?.parentElement, remotePort.current?.parentElement]) if (node) observer.observe(node);
    return () => observer.disconnect();
  }, [join, incoming, form.values.local, form.values.remote, localEndpoint, remoteEndpoint]);
  const title = t(join ? (editable ? "catalog.joins.amending" : "catalog.joins.details") : "catalog.joins.add");
  return <section className={styles.builder} aria-label={title}>
    <form ref={root} noValidate onSubmit={(event) => { event.preventDefault(); if (editable) void save(); }} onKeyDown={(event) => { if (editable && event.key === "Escape" && !event.defaultPrevented) { event.preventDefault(); void requestClose(); } }}>
    <Group justify="space-between" mb="md">
      <Group><Text fw={600}>{title}</Text><Badge variant="light">{t(join ? "catalog.joins.builder.saved" : "catalog.joins.builder.draft")}</Badge></Group>
      {editable ? <Group><Button size="sm" type="button" variant="default" onClick={() => void requestClose()}>{t("common.cancel")}</Button><Button size="sm" type="submit" loading={form.submitting}>{t(join ? "catalog.joins.save" : "catalog.joins.create")}</Button></Group> : <Group>
        <Button size="sm" type="button" variant="default" onClick={onClose}>{t("catalog.joins.backToGraph")}</Button>
        {join ? <RelationActions object={object} join={join} writable={writable} onAmend={onAmend!} onChanged={onChanged!} /> : null}
      </Group>}
    </Group>
    {saveProblem ? <Text role="alert" c="red" mb="md">{saveProblem}</Text> : null}
    <div className={styles.layout}><Stack gap="md">
      {join ? <RelationSummary object={object} join={join} /> : <>
        <SelectField editable label={t("catalog.joins.direction")} data={[{ value: "outgoing", label: t("catalog.joins.outgoingCreate") }, { value: "incoming", label: t("catalog.joins.incomingCreate") }]} {...form.fieldProps("direction")} />
        <div ref={preview} className={styles.preview} data-direction={form.values.direction} aria-label={t("catalog.joins.builder.preview")}>
          {connector ? <svg className={styles.connector} aria-hidden="true" data-draft-connector><defs><marker id={markerId} markerWidth="8" markerHeight="8" refX="8" refY="4" orient="auto" markerUnits="userSpaceOnUse"><path d="M 0 0 L 8 4 L 0 8 z" fill="currentColor" /></marker></defs><path d={connector} fill="none" stroke="currentColor" strokeWidth="2" strokeDasharray="5 3" markerEnd={`url(#${markerId})`} /></svg> : null}
          <Stack gap="xs" className={styles.endpoint}>
            <Badge variant="outline">{t(incoming ? "catalog.joins.builder.to" : "catalog.joins.builder.from")}</Badge>
            <Text size="md" fw={600} className={styles.locator}>{object.schema_name}.{object.name}</Text>
            <details><summary>{t("catalog.joins.locators")}</summary><Text size="xs" className={styles.locator}>{object.locator_key}</Text></details>
            <Text ref={localPort} data-draft-port="local" size="sm" fw={600} className={styles.port} data-selected={Boolean(form.values.local)}>{localEndpoint}</Text>
            <SelectField editable required searchable label={t("catalog.joins.localColumn")} data={columns(object)} {...form.fieldProps("local")} name="local" />
          </Stack>
          <Stack gap="xs" className={styles.endpoint}>
            <Badge variant="outline">{t(incoming ? "catalog.joins.builder.from" : "catalog.joins.builder.to")}</Badge>
            <Text size="md" fw={600} className={styles.locator}>{remoteObject ? `${remoteObject.schema_name}.${remoteObject.name}` : t("catalog.joins.otherObject")}</Text>
            <Text ref={remotePort} data-draft-port="remote" size="sm" fw={600} className={styles.port} data-selected={Boolean(form.values.remote)}>{remoteEndpoint}</Text>
            {remoteObject ? <details><summary>{t("catalog.joins.locators")}</summary><Text size="xs" className={styles.locator}>{remoteObject.locator_key}</Text></details> : null}
            <SelectField editable required searchable clearable label={t("catalog.joins.otherObject")} placeholder={t("catalog.joins.toObjectPlaceholder")} data={objects} {...form.fieldProps("remoteObject")} name="remoteObject"
              searchValue={search} onSearchChange={setSearch}
              onDropdownClose={() => setSearch(objects.find((option) => option.value === selectedRef.current)?.label ?? "")}
              onChange={(value, option) => { selectedRef.current = value; setSearch(option?.label ?? ""); if (!value) setObjects([currentOption]); form.setFieldValue("remoteObject", value); form.setFieldValue("remote", null); setRemoteObject(null); }}
              filter={({ options }) => options} nothingFoundMessage={t(searchLoading ? "catalog.joins.searchLoading" : "catalog.joins.noResults")} />
            {searchFailed ? <Button variant="subtle" size="xs" onClick={() => setSearchRetry((value) => value + 1)}>{t("common.retry")}</Button> : null}
            {truncated ? <Text size="xs" c="dimmed">{t("catalog.joins.searchTruncated")}</Text> : null}
            <SelectField editable={Boolean(remoteReady)} required searchable label={t("catalog.joins.otherColumn")} data={remoteReady ? columns(remoteObject) : []} {...form.fieldProps("remote")} name="remote" />
            {!remoteReady ? <Text size="xs" c="dimmed">{t(columnLoading ? "catalog.joins.columnsLoading" : "catalog.joins.toColumnNeedObject")}</Text> : null}
            {columnFailed ? <Button variant="subtle" size="xs" onClick={() => setColumnRetry((value) => value + 1)}>{t("common.retry")}</Button> : null}
          </Stack>
        </div>
        <Group justify="space-between"><Text size="sm" fw={600} role="status">{t("catalog.joins.builder.draft")}: {incoming ? `${remoteEndpoint} → ${localEndpoint}` : `${localEndpoint} → ${remoteEndpoint}`}</Text><Button type="button" size="xs" variant="default" onClick={() => form.setFieldValue("direction", incoming ? "outgoing" : "incoming")}>{t("catalog.joins.builder.swap")}</Button></Group>
      </>}
      <Text size="xs" c="dimmed">{t("catalog.joins.storedDirection")}</Text>
      {join ? <>
        <DisplayField label={t("catalog.joins.state")} value={<Stack gap={4}>
          <Text size="sm">{t(join.created_by_user_id ? "catalog.joins.state.manual" : "catalog.joins.state.automated")}</Text>
          {join.is_rejected ? <Badge size="xs" color="red">{t("catalog.joins.state.rejected")}</Badge> : null}
        </Stack>} />
        <DisplayField label={t("catalog.joins.createdAt")} value={<Instant value={join.created_at} />} />
        <details><summary>{t("catalog.joins.locators")}</summary><Text size="xs" className={styles.locator}>{join.from_column_locator_key ?? join.from_column_id} → {join.to_column_locator_key ?? join.to_column_id}</Text></details>
      </> : null}
      </Stack><Stack gap="md">
      <FormSection title={t("catalog.joins.definition")}>
        <SelectField editable={editable} label={t("catalog.joins.kind")} data={Array.from(new Set(["INNER", "LEFT", "RIGHT", "FULL", form.values.kind]))} {...form.fieldProps("kind")} allowDeselect={false} />
        <TextareaField editable={editable} label={t("catalog.joins.expression")} {...form.fieldProps("expression")} minRows={2} />
      </FormSection>
      <TextareaField editable={editable} required label={t("catalog.joins.evidence")} {...form.fieldProps("evidence")} name="evidence" minRows={3} />
    </Stack></div>
    </form>
  </section>;
}
