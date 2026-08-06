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
} from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import { useCallback, useEffect, useState } from "react";

import { EmptyState } from "@/components/feedback/EmptyState";
import { PageError } from "@/components/feedback/PageError";
import { PageLoader } from "@/components/feedback/PageLoader";
import { PageChrome } from "@/components/layout/PageChrome";
import {
  getCatalogObject,
  listCatalogObjects,
  listSources,
} from "@/features/sources/api";
import type { CatalogObject, Source } from "@/features/sources/types";
import { ApiError } from "@/lib/api";

export function CatalogBrowse() {
  const t = useTranslate();
  const { open } = useNotification();
  const [sources, setSources] = useState<Source[]>([]);
  const [sourceId, setSourceId] = useState<string | null>(null);
  const [q, setQ] = useState("");
  const [items, setItems] = useState<CatalogObject[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<CatalogObject | null>(null);

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

  if (loading) return <PageLoader />;
  if (error) return <PageError message={error} />;

  return (
    <PageChrome title={t("catalog.title")} description={t("catalog.description")}>
      <Group mb="md" align="flex-end">
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
        <Button variant="light" onClick={() => void loadObjects()}>
          {t("catalog.refresh")}
        </Button>
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
                    onClick={async () => {
                      try {
                        const data = await getCatalogObject(obj.id);
                        setDetail(data.object);
                      } catch (err) {
                        open?.({
                          type: "error",
                          message:
                            err instanceof ApiError ? err.detail : String(err),
                        });
                      }
                    }}
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
        size="lg"
      >
        {detail ? (
          <Stack>
            <Text size="sm" c="dimmed">
              {detail.object_type}
            </Text>
            <Table>
              <Table.Thead>
                <Table.Tr>
                  <Table.Th>#</Table.Th>
                  <Table.Th>{t("catalog.fields.column")}</Table.Th>
                  <Table.Th>{t("catalog.fields.dataType")}</Table.Th>
                  <Table.Th>null</Table.Th>
                </Table.Tr>
              </Table.Thead>
              <Table.Tbody>
                {detail.columns.map((col) => (
                  <Table.Tr key={col.id}>
                    <Table.Td>{col.ordinal}</Table.Td>
                    <Table.Td>{col.name}</Table.Td>
                    <Table.Td>{col.data_type}</Table.Td>
                    <Table.Td>{col.nullable ? "yes" : "no"}</Table.Td>
                  </Table.Tr>
                ))}
              </Table.Tbody>
            </Table>
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
