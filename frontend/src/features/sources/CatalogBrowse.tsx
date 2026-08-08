"use client";

import {
  Badge,
  Button,
  Group,
  Modal,
  Select,
  Stack,
  Table,
  Text,
  TextInput,
  Textarea,
  Title,
} from "@mantine/core";
import { useCan, useNotification, useTranslate } from "@refinedev/core";
import { useCallback, useEffect, useState } from "react";

import { EmptyState } from "@/components/feedback/EmptyState";
import { PageError } from "@/components/feedback/PageError";
import { PageLoader } from "@/components/feedback/PageLoader";
import { PageChrome } from "@/components/layout/PageChrome";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import {
  getCatalogObject,
  listCatalogObjects,
  listObjectJoins,
  listSources,
  patchColumnSemantics,
  patchObjectSemantics,
} from "@/features/sources/api";
import type {
  CatalogJoin,
  CatalogObject,
  Source,
} from "@/features/sources/types";
import { ApiError } from "@/lib/api";

function columnLabel(detail: CatalogObject, columnId: string): string {
  const col = detail.columns.find((c) => c.id === columnId);
  if (!col) return columnId;
  return `${detail.schema_name}.${detail.name}.${col.name}`;
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
  const [items, setItems] = useState<CatalogObject[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<CatalogObject | null>(null);
  const [joins, setJoins] = useState<CatalogJoin[]>([]);
  const [objectName, setObjectName] = useState("");
  const [objectDesc, setObjectDesc] = useState("");
  const [columnDrafts, setColumnDrafts] = useState<
    Record<string, { business_name: string; business_description: string }>
  >({});
  const [saving, setSaving] = useState(false);

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
      return;
    }
    try {
      const data = await listCatalogObjects(sourceId, q || undefined);
      setItems(data.items);
    } catch (err) {
      open?.({
        type: "error",
        message: err instanceof ApiError ? err.detail : String(err),
      });
    }
  }, [sourceId, q, open]);

  useEffect(() => {
    void loadSources();
  }, [loadSources]);

  useEffect(() => {
    void loadObjects();
  }, [loadObjects]);

  const openDetail = async (objectId: string) => {
    try {
      const [objRes, joinRes] = await Promise.all([
        getCatalogObject(objectId),
        listObjectJoins(objectId),
      ]);
      const obj = objRes.object;
      setDetail(obj);
      setJoins(joinRes.items);
      setObjectName(obj.business_name ?? "");
      setObjectDesc(obj.business_description ?? "");
      const drafts: Record<
        string,
        { business_name: string; business_description: string }
      > = {};
      for (const col of obj.columns) {
        drafts[col.id] = {
          business_name: col.business_name ?? "",
          business_description: col.business_description ?? "",
        };
      }
      setColumnDrafts(drafts);
    } catch (err) {
      open?.({
        type: "error",
        message: err instanceof ApiError ? err.detail : String(err),
      });
    }
  };

  const saveObjectSemantics = async () => {
    if (!detail) return;
    setSaving(true);
    try {
      const data = await patchObjectSemantics(detail.id, {
        business_name: objectName,
        business_description: objectDesc,
      });
      setDetail(data.object);
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
          data={sources.map((s) => ({ value: s.id, label: `${s.key} — ${s.name}` }))}
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
        />
      </Group>

      {!sourceId || items.length === 0 ? (
        <EmptyState message={t("catalog.empty")} />
      ) : (
        <Table striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t("catalog.fields.schema")}</Table.Th>
              <Table.Th>{t("catalog.fields.name")}</Table.Th>
              <Table.Th>{t("catalog.fields.type")}</Table.Th>
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
      )}

      <Modal
        opened={detail !== null}
        onClose={() => setDetail(null)}
        title={detail ? `${detail.schema_name}.${detail.name}` : ""}
        size="xl"
      >
        {detail ? (
          <Stack>
            <Text size="sm" c="dimmed">
              {detail.object_type}
            </Text>

            <TextInput
              label={t("catalog.semantics.businessName")}
              value={objectName}
              onChange={(e) => setObjectName(e.currentTarget.value)}
              readOnly={!writable}
            />
            <Textarea
              label={t("catalog.semantics.businessDescription")}
              value={objectDesc}
              onChange={(e) => setObjectDesc(e.currentTarget.value)}
              readOnly={!writable}
              minRows={2}
            />
            {writable ? (
              <Button
                size="sm"
                loading={saving}
                onClick={() => void saveObjectSemantics()}
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
                  <Table.Th>{t("catalog.semantics.businessName")}</Table.Th>
                  <Table.Th>{t("catalog.semantics.businessDescription")}</Table.Th>
                  {writable ? <Table.Th /> : null}
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {detail.columns.map((col) => (
                  <Table.Tr key={col.id}>
                    <Table.Td>{col.ordinal}</Table.Td>
                    <Table.Td>{col.name}</Table.Td>
                    <Table.Td>{col.data_type}</Table.Td>
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
                          value={columnDrafts[col.id]?.business_description ?? ""}
                          onChange={(e) =>
                            setColumnDrafts((prev) => ({
                              ...prev,
                              [col.id]: {
                                business_name: prev[col.id]?.business_name ?? "",
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
                    <Table.Th>{t("catalog.joins.createdAt")}</Table.Th>
                  </Table.Tr>
                </Table.Thead>
                <Table.Tbody>
                  {joins.map((join) => (
                    <Table.Tr key={join.id}>
                      <Table.Td>
                        {columnLabel(detail, join.from_column_id)}
                      </Table.Td>
                      <Table.Td>
                        {columnLabel(detail, join.to_column_id)}
                      </Table.Td>
                      <Table.Td>{join.evidence}</Table.Td>
                      <Table.Td>{join.created_at}</Table.Td>
                    </Table.Tr>
                  ))}
                </Table.Tbody>
              </Table>
            )}

            {detail.ddl ? (
              <Text component="pre" style={{ whiteSpace: "pre-wrap" }} size="xs">
                {detail.ddl}
              </Text>
            ) : null}
          </Stack>
        ) : null}
      </Modal>
    </PageChrome>
  );
}
