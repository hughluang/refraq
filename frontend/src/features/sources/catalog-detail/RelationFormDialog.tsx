"use client";

import { Button, Stack, Text } from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import { useEffect, useRef, useState } from "react";
import { FormDialog } from "@/components/form/FormDialog";
import { FormSection } from "@/components/form/FormSection";
import { SelectField } from "@/components/form/SelectField";
import { TextField } from "@/components/form/TextField";
import { TextareaField } from "@/components/form/TextareaField";
import { useConsoleForm } from "@/components/form/useConsoleForm";
import { presentSaveFailure } from "@/components/feedback/presentSaveFailure";
import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { getCatalogObject, searchCatalogObjects } from "@/features/sources/api/catalog";
import { createJoin, patchJoin } from "@/features/sources/api/joins";
import type { CatalogJoin, CatalogObject } from "@/features/sources/types";
import { useSearchDebounce } from "@/hooks/useSearchDebounce";
import { mergeSelectedOption, type JoinSelectOption } from "./joinEdges";
import { RelationSummary } from "./RelationSummary";

type Values = { direction: string; local: string | null; remoteObject: string | null; remote: string | null; kind: string; expression: string; evidence: string };
type Props = { object: CatalogObject; join?: CatalogJoin; onClose: () => void; onSaved: () => Promise<void> };

export function RelationFormDialog({ object, join, onClose, onSaved }: Props) {
  const t = useTranslate();
  const { open } = useNotification();
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const form = useConsoleForm<Values>({
    initialValues: { direction: "outgoing", local: null, remoteObject: null, remote: null, kind: join?.join_kind ?? "INNER", expression: join?.join_expression ?? "", evidence: join?.evidence ?? "" },
    validate: {
      local: (value) => !join && !value ? t("catalog.joins.columnRequired") : null,
      remoteObject: (value) => !join && !value ? t("catalog.joins.objectRequired") : null,
      remote: (value, values) => join ? null : !value ? t("catalog.joins.columnRequired") : value === values.local ? t("catalog.joins.distinctColumns") : null,
      evidence: (value) => value.trim() ? null : t("catalog.joins.evidenceRequired"),
    },
  });
  const [search, setSearch] = useState("");
  const query = useSearchDebounce(search).trim();
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
  const searchRef = useRef(search);
  searchRef.current = search;
  useEffect(() => {
    if (join) return;
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
    try {
      const details = { evidence: values.evidence.trim(), join_kind: values.kind, join_expression: join && values.expression === (join.join_expression ?? "") ? join.join_expression ?? null : values.expression };
      if (join) await patchJoin(join.id, details);
      else {
        const incoming = values.direction === "incoming";
        await createJoin({ ...details, join_expression: values.expression || null, from_column_id: (incoming ? values.remote : values.local)!, to_column_id: (incoming ? values.local : values.remote)! });
      }
    } catch (error) {
      if (alive.current) presentSaveFailure(t, error, (failure) => form.applyApiError(failure, { from_column_id: form.values.direction === "incoming" ? "remote" : "local", to_column_id: form.values.direction === "incoming" ? "local" : "remote", join_kind: "kind", join_expression: "expression" }));
      throw error;
    }
    if (!alive.current) return;
    form.markSaved();
    open?.({ type: "success", message: t("catalog.joins.saved") });
    await onSaved();
  });
  return <FormDialog opened title={t(join ? "catalog.joins.amending" : "catalog.joins.add")} onClose={onClose} dirty={form.dirty} submitting={form.submitting} submitLabel={t(join ? "catalog.joins.save" : "catalog.joins.create")} onSubmit={() => void save()} size="lg">
    <Stack gap="lg">
      {join ? <RelationSummary object={object} join={join} /> : <>
        <SelectField editable label={t("catalog.joins.direction")} data={[{ value: "outgoing", label: t("catalog.joins.outgoingCreate") }, { value: "incoming", label: t("catalog.joins.incomingCreate") }]} {...form.fieldProps("direction")} />
        <FormSection title={t("catalog.joins.endpoints")} description={t("catalog.joins.pairHelp")}>
          <Stack gap="xs">
            <Text size="sm" fw={500}>{object.schema_name}.{object.name}</Text>
            <SelectField editable required searchable label={t("catalog.joins.localColumn")} data={columns(object)} {...form.fieldProps("local")} name="local" />
          </Stack>
          <Stack gap="xs">
            <TextField editable label={t("catalog.joins.searchObjects")} value={search} onChange={(event) => setSearch(event.currentTarget.value)} placeholder={t("catalog.joins.toObjectPlaceholder")} />
            <SelectField editable required searchable clearable label={t("catalog.joins.otherObject")} data={objects} {...form.fieldProps("remoteObject")} name="remoteObject" onChange={(value) => { form.setFieldValue("remoteObject", value); form.setFieldValue("remote", null); setRemoteObject(null); }} filter={({ options }) => options} nothingFoundMessage={t(searchLoading ? "catalog.joins.searchLoading" : "catalog.joins.noResults")} />
            {searchFailed ? <Button variant="subtle" size="xs" onClick={() => setSearchRetry((value) => value + 1)}>{t("common.retry")}</Button> : null}
            {truncated ? <Text size="xs" c="dimmed">{t("catalog.joins.searchTruncated")}</Text> : null}
            <SelectField editable={Boolean(remoteReady)} required searchable label={t("catalog.joins.otherColumn")} data={remoteReady ? columns(remoteObject) : []} {...form.fieldProps("remote")} name="remote" />
            {!remoteReady ? <Text size="xs" c="dimmed">{t(columnLoading ? "catalog.joins.columnsLoading" : "catalog.joins.toColumnNeedObject")}</Text> : null}
            {columnFailed ? <Button variant="subtle" size="xs" onClick={() => setColumnRetry((value) => value + 1)}>{t("common.retry")}</Button> : null}
          </Stack>
        </FormSection>
        <Text size="sm" fw={500}>{form.values.direction === "incoming" ? `${remoteObject?.name ?? "…"} → ${object.name}` : `${object.name} → ${remoteObject?.name ?? "…"}`}</Text>
      </>}
      <Text size="xs" c="dimmed">{t("catalog.joins.storedDirection")}</Text>
      <FormSection title={t("catalog.joins.definition")}>
        <SelectField editable label={t("catalog.joins.kind")} data={Array.from(new Set(["INNER", "LEFT", "RIGHT", "FULL", form.values.kind]))} {...form.fieldProps("kind")} allowDeselect={false} />
        <TextareaField editable label={t("catalog.joins.expression")} {...form.fieldProps("expression")} minRows={2} />
      </FormSection>
      <TextareaField editable required label={t("catalog.joins.evidence")} {...form.fieldProps("evidence")} name="evidence" minRows={3} />
    </Stack>
  </FormDialog>;
}
