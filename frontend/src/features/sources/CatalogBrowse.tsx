"use client";

import {
  Badge,
  Button,
  Group,
  Modal,
  NumberInput,
  Pagination,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Textarea,
  Title,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { useCan, useNotification, useTranslate } from "@refinedev/core";
import { useCallback, useEffect, useState } from "react";

import { EmptyState } from "@/components/feedback/EmptyState";
import { PageError } from "@/components/feedback/PageError";
import { PageLoader } from "@/components/feedback/PageLoader";
import { PageChrome } from "@/components/layout/PageChrome";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import {
  deleteJoin,
  getCatalogObject,
  listCatalogObjects,
  listObjectJoins,
  listSources,
  patchColumnSemantics,
  patchObjectSemantics,
  searchCatalogColumns,
  upsertJoin,
} from "@/features/sources/api";
import type {
  CatalogJoin,
  CatalogObject,
  ObjectCategory,
  Source,
} from "@/features/sources/types";
import { ApiError } from "@/lib/api";

const PAGE_SIZE = 100;

const OBJECT_CATEGORY_OPTIONS: { value: ObjectCategory; label: string }[] = [
  { value: "transaction_fact", label: "transaction_fact" },
  { value: "master_data", label: "master_data" },
  { value: "dimension", label: "dimension" },
  { value: "reference", label: "reference" },
  { value: "event", label: "event" },
];

type ObjectSemanticsFormValues = {
  business_name: string;
  business_description: string;
  object_category: string | null;
  grain_description: string;
  business_domain: string;
  open_questions: string;
  confidence: number | string;
};

type ColumnDraft = {
  business_name: string;
  business_description: string;
};

type SelectOption = { value: string; label: string };

function columnLabel(detail: CatalogObject, columnId: string): string {
  const col = detail.columns.find((c) => c.id === columnId);
  if (!col) return columnId;
  return `${col.name} · ${col.locator_key}`;
}

function emptyObjectForm(): ObjectSemanticsFormValues {
  return {
    business_name: "",
    business_description: "",
    object_category: null,
    grain_description: "",
    business_domain: "",
    open_questions: "",
    confidence: "",
  };
}

function formFromObject(obj: CatalogObject): ObjectSemanticsFormValues {
  return {
    business_name: obj.business_name ?? "",
    business_description: obj.business_description ?? "",
    object_category: obj.object_category ? String(obj.object_category) : null,
    grain_description: obj.grain_description ?? "",
    business_domain: obj.business_domain ?? "",
    open_questions: (obj.open_questions ?? []).join("\n"),
    confidence: obj.confidence ?? "",
  };
}

export function CatalogBrowse() {
  const t = useTranslate();
  const { open } = useNotification();
  const { data: canWrite } = useCan({
    resource: ModuleId.catalog,
    action: ModuleAction.edit,
  });
  const writable = Boolean(canWrite?.can);

  const [sources, setSources] = useState<Source[]>([]);
  const [sourceId, setSourceId] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState(0);
  const [items, setItems] = useState<CatalogObject[]>([]);
  const [listLoading, setListLoading] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<CatalogObject | null>(null);
  const [joins, setJoins] = useState<CatalogJoin[]>([]);
  const [columnDrafts, setColumnDrafts] = useState<Record<string, ColumnDraft>>(
    {},
  );
  const [saving, setSaving] = useState(false);
  const [joinFromId, setJoinFromId] = useState<string | null>(null);
  const [joinToId, setJoinToId] = useState<string | null>(null);
  const [joinEvidence, setJoinEvidence] = useState("");
  const [toSearch, setToSearch] = useState("");
  const [debouncedToSearch, setDebouncedToSearch] = useState("");
  const [toOptions, setToOptions] = useState<SelectOption[]>([]);
  const [toSearchLoading, setToSearchLoading] = useState(false);

  const objectForm = useForm<ObjectSemanticsFormValues>({
    initialValues: emptyObjectForm(),
  });

  const loadSources = useCallback(async () => {
    setLoading(true);
    try {
      const data = await listSources();
      setSources(data.items);
      if (!sourceId && data.items[0]) {
        setSourceId(data.items[0].id);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err));
    } finally {
      setLoading(false);
    }
  }, [sourceId]);

  const loadObjects = useCallback(async () => {
    if (!sourceId) {
      setItems([]);
      setTotal(0);
      return;
    }
    setListLoading(true);
    try {
      const offset = (page - 1) * PAGE_SIZE;
      const data = await listCatalogObjects(sourceId, debouncedQ || undefined, {
        limit: PAGE_SIZE,
        offset,
      });
      setItems(data.items);
      setTotal(data.total);
    } catch (err) {
      open?.({
        type: "error",
        message: err instanceof ApiError ? err.detail : String(err),
      });
    } finally {
      setListLoading(false);
    }
  }, [sourceId, debouncedQ, page, open]);

  useEffect(() => {
    void loadSources();
  }, [loadSources]);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedQ(q), 300);
    return () => window.clearTimeout(timer);
  }, [q]);

  useEffect(() => {
    setPage(1);
  }, [sourceId, debouncedQ]);

  useEffect(() => {
    void loadObjects();
  }, [loadObjects]);

  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedToSearch(toSearch), 300);
    return () => window.clearTimeout(timer);
  }, [toSearch]);

  useEffect(() => {
    if (!detail) return;
    const query = debouncedToSearch.trim();
    if (!query) {
      setToOptions((prev) =>
        joinToId ? prev.filter((o) => o.value === joinToId) : [],
      );
      return;
    }

    let cancelled = false;
    setToSearchLoading(true);
    void searchCatalogColumns({
      q: query,
      source_id: detail.source_id,
      limit: 20,
    })
      .then((data) => {
        if (cancelled) return;
        const next = data.items.map((c) => ({
          value: c.id,
          label: `${c.name} · ${c.locator_key}`,
        }));
        setToOptions((prev) => {
          if (!joinToId || next.some((o) => o.value === joinToId)) return next;
          const selected = prev.find((o) => o.value === joinToId);
          return selected ? [selected, ...next] : next;
        });
      })
      .catch((err) => {
        if (cancelled) return;
        open?.({
          type: "error",
          message: err instanceof ApiError ? err.detail : String(err),
        });
      })
      .finally(() => {
        if (!cancelled) setToSearchLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [debouncedToSearch, detail, joinToId, open]);

  const openDetail = async (objectId: string) => {
    try {
      const [objRes, joinRes] = await Promise.all([
        getCatalogObject(objectId),
        listObjectJoins(objectId),
      ]);
      const obj = objRes.object;
      setDetail(obj);
      setJoins(joinRes.items);
      objectForm.setValues(formFromObject(obj));
      const drafts: Record<string, ColumnDraft> = {};
      for (const col of obj.columns) {
        drafts[col.id] = {
          business_name: col.business_name ?? "",
          business_description: col.business_description ?? "",
        };
      }
      setColumnDrafts(drafts);
      setJoinFromId(obj.columns[0]?.id ?? null);
      setJoinToId(null);
      setJoinEvidence("");
      setToSearch("");
      setDebouncedToSearch("");
      setToOptions([]);
    } catch (err) {
      open?.({
        type: "error",
        message: err instanceof ApiError ? err.detail : String(err),
      });
    }
  };

  const saveObjectSemantics = async (values: ObjectSemanticsFormValues) => {
    if (!detail) return;
    setSaving(true);
    try {
      const openQuestions = values.open_questions
        .split("\n")
        .map((line) => line.trim())
        .filter(Boolean);
      const confidenceRaw =
        values.confidence === "" || values.confidence === null
          ? null
          : Number(values.confidence);
      const data = await patchObjectSemantics(detail.id, {
        business_name: values.business_name,
        business_description: values.business_description,
        object_category: (values.object_category as ObjectCategory | null) || null,
        grain_description: values.grain_description || null,
        business_domain: values.business_domain || null,
        open_questions: openQuestions,
        confidence:
          confidenceRaw !== null && Number.isFinite(confidenceRaw)
            ? confidenceRaw
            : null,
      });
      setDetail(data.object);
      objectForm.setValues(formFromObject(data.object));
      open?.({ type: "success", message: t("catalog.semantics.saved") });
      void loadObjects();
    } catch (err) {
      open?.({
        type: "error",
        message: err instanceof ApiError ? err.detail : String(err),
      });
    } finally {
      setSaving(false);
    }
  };

  const saveColumnSemantics = async (columnId: string) => {
    const draft = columnDrafts[columnId];
    if (!draft || !detail) return;
    setSaving(true);
    try {
      const data = await patchColumnSemantics(columnId, {
        business_name: draft.business_name,
        business_description: draft.business_description,
      });
      setDetail({
        ...detail,
        columns: detail.columns.map((c) =>
          c.id === columnId ? { ...c, ...data.column } : c,
        ),
      });
      open?.({ type: "success", message: t("catalog.semantics.saved") });
    } catch (err) {
      open?.({
        type: "error",
        message: err instanceof ApiError ? err.detail : String(err),
      });
    } finally {
      setSaving(false);
    }
  };

  const saveJoinEdge = async () => {
    if (!detail || !joinFromId) return;
    const evidence = joinEvidence.trim();
    if (!evidence) {
      open?.({ type: "error", message: t("catalog.joins.evidenceRequired") });
      return;
    }
    if (!joinToId) {
      open?.({ type: "error", message: t("catalog.joins.toColumnRequired") });
      return;
    }
    setSaving(true);
    try {
      await upsertJoin({
        from_column_id: joinFromId,
        to_column_id: joinToId,
        evidence,
      });
      const joinRes = await listObjectJoins(detail.id);
      setJoins(joinRes.items);
      setJoinEvidence("");
      open?.({ type: "success", message: t("catalog.joins.saved") });
    } catch (err) {
      open?.({
        type: "error",
        message: err instanceof ApiError ? err.detail : String(err),
      });
    } finally {
      setSaving(false);
    }
  };

  const removeJoinEdge = async (joinId: string) => {
    if (!detail) return;
    setSaving(true);
    try {
      await deleteJoin(joinId);
      const joinRes = await listObjectJoins(detail.id);
      setJoins(joinRes.items);
      open?.({ type: "success", message: t("catalog.joins.deleted") });
    } catch (err) {
      open?.({
        type: "error",
        message: err instanceof ApiError ? err.detail : String(err),
      });
    } finally {
      setSaving(false);
    }
  };

  if (loading) return <PageLoader />;
  if (error) return <PageError message={error} />;

  const refreshAction = (
    <Button size="sm" variant="light" onClick={() => void loadObjects()}>
      {t("catalog.refresh")}
    </Button>
  );

  return (
    <PageChrome
      title={t("catalog.title")}
      description={t("catalog.description")}
      actions={refreshAction}
    >
      <Group mb="md">
        <Select
          label={t("catalog.fields.source")}
          data={sources.map((s) => ({
            value: s.id,
            label: `${s.key} — ${s.name}`,
          }))}
          value={sourceId}
          onChange={setSourceId}
          searchable
          w={320}
        />
        <TextInput
          label={t("catalog.fields.search")}
          value={q}
          onChange={(e) => setQ(e.currentTarget.value)}
          w={220}
          rightSection={listLoading ? <Text size="xs">…</Text> : null}
        />
      </Group>

      {!sourceId || total === 0 ? (
        <EmptyState message={t("catalog.empty")} />
      ) : (
        <Stack gap="sm">
          <Table striped highlightOnHover>
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t("catalog.fields.schema")}</Table.Th>
                <Table.Th>{t("catalog.fields.name")}</Table.Th>
                <Table.Th>{t("catalog.fields.type")}</Table.Th>
                <Table.Th>{t("catalog.fields.locator")}</Table.Th>
                <Table.Th>{t("catalog.fields.present")}</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {items.map((obj) => (
                <Table.Tr key={obj.id}>
                  <Table.Td>{obj.schema_name}</Table.Td>
                  <Table.Td>{obj.name}</Table.Td>
                  <Table.Td>{obj.object_type}</Table.Td>
                  <Table.Td>
                    <Text
                      size="xs"
                      c="dimmed"
                      style={{ wordBreak: "break-all" }}
                    >
                      {obj.locator_key}
                    </Text>
                  </Table.Td>
                  <Table.Td>
                    <Badge color={obj.is_present ? "green" : "gray"}>
                      {obj.is_present ? "present" : "absent"}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    <Button
                      size="xs"
                      variant="light"
                      onClick={() => void openDetail(obj.id)}
                    >
                      {t("catalog.detail")}
                    </Button>
                  </Table.Td>
                </Table.Tr>
              ))}
            </Table.Tbody>
          </Table>
          <Group justify="space-between">
            <Text size="sm" c="dimmed">
              {t("catalog.list.showing", {
                from: (page - 1) * PAGE_SIZE + 1,
                to: Math.min(page * PAGE_SIZE, total),
                total,
              })}
            </Text>
            <Pagination
              value={page}
              onChange={setPage}
              total={Math.max(1, Math.ceil(total / PAGE_SIZE))}
            />
          </Group>
        </Stack>
      )}

      <Modal
        opened={detail !== null}
        onClose={() => {
          setDetail(null);
          objectForm.reset();
        }}
        title={detail ? `${detail.schema_name}.${detail.name}` : ""}
        size="xl"
      >
        {detail ? (
          <Stack>
            <Group gap="sm">
              <Text size="sm" c="dimmed">
                {detail.object_type}
              </Text>
              <Badge color={detail.business_semantics_ready ? "green" : "gray"}>
                {detail.business_semantics_ready
                  ? t("catalog.semantics.ready")
                  : t("catalog.semantics.notReady")}
              </Badge>
            </Group>
            <Text size="xs" c="dimmed" style={{ wordBreak: "break-all" }}>
              {detail.locator_key}
            </Text>
            <Text size="sm" c="dimmed">
              {t("catalog.semantics.provenance")}:{" "}
              {detail.semantic_source ?? "—"}
            </Text>

            <TextInput
              label={t("catalog.semantics.businessName")}
              {...objectForm.getInputProps("business_name")}
              readOnly={!writable}
            />
            <Textarea
              label={t("catalog.semantics.businessDescription")}
              {...objectForm.getInputProps("business_description")}
              readOnly={!writable}
              minRows={2}
            />
            <Select
              label={t("catalog.semantics.category")}
              data={OBJECT_CATEGORY_OPTIONS}
              clearable
              searchable
              {...objectForm.getInputProps("object_category")}
              disabled={!writable}
            />
            <Textarea
              label={t("catalog.semantics.grain")}
              {...objectForm.getInputProps("grain_description")}
              readOnly={!writable}
              minRows={2}
            />
            <TextInput
              label={t("catalog.semantics.domain")}
              {...objectForm.getInputProps("business_domain")}
              readOnly={!writable}
            />
            <Textarea
              label={t("catalog.semantics.openQuestions")}
              {...objectForm.getInputProps("open_questions")}
              readOnly={!writable}
              minRows={3}
            />
            <NumberInput
              label={t("catalog.semantics.confidence")}
              {...objectForm.getInputProps("confidence")}
              min={0}
              max={1}
              step={0.1}
              decimalScale={2}
              allowDecimal
              clampBehavior="strict"
              disabled={!writable}
            />
            {writable ? (
              <Button
                size="sm"
                loading={saving}
                onClick={() => void saveObjectSemantics(objectForm.values)}
                w="fit-content"
              >
                {t("catalog.semantics.saveObject")}
              </Button>
            ) : null}

            <Table>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>#</Table.Th>
                  <Table.Th>{t("catalog.fields.column")}</Table.Th>
                  <Table.Th>{t("catalog.fields.dataType")}</Table.Th>
                  <Table.Th>{t("catalog.fields.nullable")}</Table.Th>
                  <Table.Th>{t("catalog.semantics.businessName")}</Table.Th>
                  <Table.Th>
                    {t("catalog.semantics.businessDescription")}
                  </Table.Th>
                  {writable ? <Table.Th /> : null}
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {detail.columns.map((col) => (
                  <Table.Tr key={col.id}>
                    <Table.Td>{col.ordinal}</Table.Td>
                    <Table.Td>
                      <Stack gap={2}>
                        <Text size="sm">{col.name}</Text>
                        <Text
                          size="xs"
                          c="dimmed"
                          style={{ wordBreak: "break-all" }}
                        >
                          {col.locator_key}
                        </Text>
                      </Stack>
                    </Table.Td>
                    <Table.Td>{col.data_type}</Table.Td>
                    <Table.Td>
                      {col.nullable
                        ? t("catalog.fields.yes")
                        : t("catalog.fields.no")}
                    </Table.Td>
                    <Table.Td>
                      {writable ? (
                        <TextInput
                          size="xs"
                          value={columnDrafts[col.id]?.business_name ?? ""}
                          onChange={(e) =>
                            setColumnDrafts((prev) => ({
                              ...prev,
                              [col.id]: {
                                business_name: e.currentTarget.value,
                                business_description:
                                  prev[col.id]?.business_description ?? "",
                              },
                            }))
                          }
                        />
                      ) : (
                        col.business_name ?? "—"
                      )}
                    </Table.Td>
                    <Table.Td>
                      {writable ? (
                        <TextInput
                          size="xs"
                          value={
                            columnDrafts[col.id]?.business_description ?? ""
                          }
                          onChange={(e) =>
                            setColumnDrafts((prev) => ({
                              ...prev,
                              [col.id]: {
                                business_name:
                                  prev[col.id]?.business_name ?? "",
                                business_description: e.currentTarget.value,
                              },
                            }))
                          }
                        />
                      ) : (
                        col.business_description ?? "—"
                      )}
                    </Table.Td>
                    {writable ? (
                      <Table.Td>
                        <Button
                          size="xs"
                          variant="light"
                          loading={saving}
                          onClick={() => void saveColumnSemantics(col.id)}
                        >
                          {t("catalog.semantics.saveColumn")}
                        </Button>
                      </Table.Td>
                    ) : null}
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>

            <Title order={5}>{t("catalog.joins.title")}</Title>
            {writable ? (
              <Stack gap="xs">
                <Text size="sm" fw={500}>
                  {t("catalog.joins.add")}
                </Text>
                <Group align="flex-end" grow>
                  <Select
                    label={t("catalog.joins.from")}
                    data={detail.columns.map((c) => ({
                      value: c.id,
                      label: `${c.name} · ${c.locator_key}`,
                    }))}
                    value={joinFromId}
                    onChange={setJoinFromId}
                    searchable
                  />
                  <Select
                    label={t("catalog.joins.toColumn")}
                    data={toOptions}
                    value={joinToId}
                    onChange={setJoinToId}
                    searchable
                    searchValue={toSearch}
                    onSearchChange={setToSearch}
                    filter={({ options }) => options}
                    clearable
                    nothingFoundMessage={
                      toSearchLoading
                        ? "…"
                        : debouncedToSearch.trim()
                          ? undefined
                          : t("catalog.joins.toColumnPlaceholder")
                    }
                    placeholder={t("catalog.joins.toColumnPlaceholder")}
                    rightSection={
                      toSearchLoading ? <Text size="xs">…</Text> : undefined
                    }
                  />
                </Group>
                <Textarea
                  label={t("catalog.joins.evidence")}
                  value={joinEvidence}
                  onChange={(e) => setJoinEvidence(e.currentTarget.value)}
                  minRows={2}
                  required
                />
                <Button
                  size="sm"
                  w="fit-content"
                  loading={saving}
                  onClick={() => void saveJoinEdge()}
                >
                  {t("catalog.joins.save")}
                </Button>
              </Stack>
            ) : null}
            {joins.length === 0 ? (
              <Text size="sm" c="dimmed">
                {t("catalog.joins.empty")}
              </Text>
            ) : (
              <Table>
                <Table.Thead>
                  <Table.Tr>
                    <Table.Th>{t("catalog.joins.from")}</Table.Th>
                    <Table.Th>{t("catalog.joins.to")}</Table.Th>
                    <Table.Th>{t("catalog.joins.evidence")}</Table.Th>
                    <Table.Th>{t("catalog.joins.kind")}</Table.Th>
                    <Table.Th>{t("catalog.joins.origin")}</Table.Th>
                    <Table.Th>{t("catalog.joins.createdAt")}</Table.Th>
                    {writable ? <Table.Th /> : null}
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {joins.map((join) => (
                    <Table.Tr key={join.id}>
                      <Table.Td>
                        <Text size="xs" style={{ wordBreak: "break-all" }}>
                          {join.from_column_locator_key ??
                            columnLabel(detail, join.from_column_id)}
                        </Text>
                      </Table.Td>
                      <Table.Td>
                        <Text size="xs" style={{ wordBreak: "break-all" }}>
                          {join.to_column_locator_key ??
                            columnLabel(detail, join.to_column_id)}
                        </Text>
                      </Table.Td>
                      <Table.Td>{join.evidence}</Table.Td>
                      <Table.Td>{join.join_kind ?? "INNER"}</Table.Td>
                      <Table.Td>{join.origin ?? "—"}</Table.Td>
                      <Table.Td>{join.created_at}</Table.Td>
                      {writable ? (
                        <Table.Td>
                          <Button
                            size="xs"
                            variant="subtle"
                            color="red"
                            loading={saving}
                            onClick={() => void removeJoinEdge(join.id)}
                          >
                            {t("catalog.joins.delete")}
                          </Button>
                        </Table.Td>
                      ) : null}
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            )}

            {detail.ddl ? (
              <Text
                component="pre"
                style={{ whiteSpace: "pre-wrap" }}
                size="xs"
              >
                {detail.ddl}
              </Text>
            ) : null}
          </Stack>
        ) : null}
      </Modal>
    </PageChrome>
  );
}
