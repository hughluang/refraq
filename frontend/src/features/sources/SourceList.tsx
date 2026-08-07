"use client";

import {
  Badge,
  Button,
  Modal,
  NumberInput,
  Select,
  Stack,
  Table,
  TextInput,
  Textarea,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import {
  CanAccess,
  useCan,
  useNotification,
  useTranslate,
} from "@refinedev/core";
import { useCallback, useEffect, useState } from "react";

import { EmptyState } from "@/components/feedback/EmptyState";
import { PageError } from "@/components/feedback/PageError";
import { PageLoader } from "@/components/feedback/PageLoader";
import { PageChrome } from "@/components/layout/PageChrome";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import {
  createConnection,
  createSource,
  listConnections,
  listSources,
  patchConnection,
  rotateConnectionSecret,
} from "@/features/sources/api";
import type { Connection, Source } from "@/features/sources/types";
import { ApiError } from "@/lib/api";

type SourceForm = {
  key: string;
  name: string;
  database_name: string;
  schema_filter: string;
  description: string;
};

type ConnForm = {
  name: string;
  engine: string;
  host: string;
  port: number;
  username: string;
  password: string;
};

export function SourceList() {
  const t = useTranslate();
  const { open } = useNotification();
  const { data: canWrite } = useCan({
    resource: ModuleId.sources,
    action: ModuleAction.create,
  });

  const [items, setItems] = useState<Source[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [connSource, setConnSource] = useState<Source | null>(null);
  const [existingConn, setExistingConn] = useState<Connection | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await listSources();
      setItems(data.items);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const sourceForm = useForm<SourceForm>({
    initialValues: {
      key: "",
      name: "",
      database_name: "",
      schema_filter: "",
      description: "",
    },
    validate: {
      key: (v) => (v.trim() ? null : t("sources.validation.required")),
      name: (v) => (v.trim() ? null : t("sources.validation.required")),
      database_name: (v) =>
        v.trim() ? null : t("sources.validation.required"),
    },
  });

  const connForm = useForm<ConnForm>({
    initialValues: {
      name: "",
      engine: "postgresql",
      host: "",
      port: 5432,
      username: "",
      password: "",
    },
    validate: {
      name: (v) => (v.trim() ? null : t("sources.validation.required")),
      host: (v) => (v.trim() ? null : t("sources.validation.required")),
      username: (v) =>
        existingConn ? null : v.trim() ? null : t("sources.validation.required"),
      password: (v) =>
        existingConn ? null : v.trim() ? null : t("sources.validation.required"),
    },
  });

  async function openConnection(source: Source) {
    setConnSource(source);
    setBusy(true);
    try {
      const data = await listConnections(source.id);
      const conn = data.items[0] ?? null;
      setExistingConn(conn);
      connForm.setValues(
        conn
          ? {
              name: conn.name,
              engine: conn.engine,
              host: conn.host,
              port: conn.port,
              username: "",
              password: "",
            }
          : {
              name: `${source.name} primary`,
              engine: "postgresql",
              host: "",
              port: 5432,
              username: "",
              password: "",
            },
      );
    } catch (err) {
      open?.({
        type: "error",
        message: err instanceof ApiError ? err.detail : String(err),
      });
    } finally {
      setBusy(false);
    }
  }

  const createAction = (
    <CanAccess resource={ModuleId.sources} action={ModuleAction.create}>
      <Button size="sm" onClick={() => setCreateOpen(true)}>
        {t("sources.create")}
      </Button>
    </CanAccess>
  );

  if (loading) {
    return <PageLoader />;
  }
  if (error) {
    return <PageError message={error} />;
  }

  return (
    <PageChrome
      title={t("sources.title")}
      description={t("sources.description")}
      actions={createAction}
    >
      {items.length === 0 ? (
        <EmptyState message={t("sources.empty")} />
      ) : (
        <Table striped highlightOnHover>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t("sources.fields.key")}</Table.Th>
              <Table.Th>{t("sources.fields.name")}</Table.Th>
              <Table.Th>{t("sources.fields.database")}</Table.Th>
              <Table.Th>{t("sources.fields.status")}</Table.Th>
              <Table.Th>{t("sources.fields.actions")}</Table.Th>
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {items.map((source) => (
              <Table.Tr key={source.id}>
                <Table.Td>{source.key}</Table.Td>
                <Table.Td>{source.name}</Table.Td>
                <Table.Td>{source.database_name}</Table.Td>
                <Table.Td>
                  <Badge color={source.status === "active" ? "green" : "gray"}>
                    {source.status}
                  </Badge>
                </Table.Td>
                <Table.Td>
                  {canWrite?.can ? (
                    <Button
                      size="xs"
                      variant="light"
                      onClick={() => void openConnection(source)}
                    >
                      {t("sources.connection.manage")}
                    </Button>
                  ) : null}
                </Table.Td>
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}

      <Modal
        opened={createOpen}
        onClose={() => setCreateOpen(false)}
        title={t("sources.create")}
      >
        <form
          onSubmit={sourceForm.onSubmit(async (values) => {
            setBusy(true);
            try {
              await createSource({
                key: values.key.trim(),
                name: values.name.trim(),
                kind: "database",
                database_name: values.database_name.trim(),
                schema_filter: values.schema_filter.trim() || null,
                description: values.description.trim() || null,
              });
              open?.({ type: "success", message: t("sources.create.success") });
              setCreateOpen(false);
              sourceForm.reset();
              await load();
            } catch (err) {
              open?.({
                type: "error",
                message: err instanceof ApiError ? err.detail : String(err),
              });
            } finally {
              setBusy(false);
            }
          })}
        >
          <Stack>
            <TextInput
              label={t("sources.fields.key")}
              {...sourceForm.getInputProps("key")}
            />
            <TextInput
              label={t("sources.fields.name")}
              {...sourceForm.getInputProps("name")}
            />
            <TextInput
              label={t("sources.fields.database")}
              {...sourceForm.getInputProps("database_name")}
            />
            <TextInput
              label={t("sources.fields.schemaFilter")}
              {...sourceForm.getInputProps("schema_filter")}
            />
            <Textarea
              label={t("sources.fields.description")}
              {...sourceForm.getInputProps("description")}
            />
            <Button type="submit" loading={busy}>
              {t("sources.create")}
            </Button>
          </Stack>
        </form>
      </Modal>

      <Modal
        opened={connSource !== null}
        onClose={() => setConnSource(null)}
        title={
          existingConn
            ? t("sources.connection.edit")
            : t("sources.connection.create")
        }
      >
        <form
          onSubmit={connForm.onSubmit(async (values) => {
            if (!connSource) return;
            setBusy(true);
            try {
              if (existingConn) {
                await patchConnection(existingConn.id, {
                  name: values.name.trim(),
                  engine: values.engine as "postgresql" | "mssql" | "oracle",
                  host: values.host.trim(),
                  port: Number(values.port),
                });
                if (values.username.trim() && values.password) {
                  await rotateConnectionSecret(existingConn.id, {
                    username: values.username.trim(),
                    password: values.password,
                  });
                }
              } else {
                await createConnection(connSource.id, {
                  name: values.name.trim(),
                  engine: values.engine as "postgresql" | "mssql" | "oracle",
                  host: values.host.trim(),
                  port: Number(values.port),
                  secret: {
                    username: values.username.trim(),
                    password: values.password,
                  },
                });
              }
              open?.({
                type: "success",
                message: t("sources.connection.success"),
              });
              setConnSource(null);
            } catch (err) {
              open?.({
                type: "error",
                message: err instanceof ApiError ? err.detail : String(err),
              });
            } finally {
              setBusy(false);
            }
          })}
        >
          <Stack>
            <TextInput
              label={t("sources.fields.connName")}
              {...connForm.getInputProps("name")}
            />
            <Select
              label={t("sources.fields.engine")}
              data={[
                { value: "postgresql", label: "PostgreSQL" },
                { value: "mssql", label: "MSSQL" },
                { value: "oracle", label: "Oracle" },
              ]}
              {...connForm.getInputProps("engine")}
            />
            <TextInput
              label={t("sources.fields.host")}
              {...connForm.getInputProps("host")}
            />
            <NumberInput
              label={t("sources.fields.port")}
              {...connForm.getInputProps("port")}
            />
            <TextInput
              label={t("sources.fields.username")}
              description={
                existingConn ? t("sources.connection.secretHint") : undefined
              }
              {...connForm.getInputProps("username")}
            />
            <TextInput
              type="password"
              label={t("sources.fields.password")}
              {...connForm.getInputProps("password")}
            />
            <Button type="submit" loading={busy}>
              {t("actions.save")}
            </Button>
          </Stack>
        </form>
      </Modal>
    </PageChrome>
  );
}
