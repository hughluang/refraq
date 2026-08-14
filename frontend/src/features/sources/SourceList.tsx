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
  Tooltip,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { CanAccess, useCan, useNotification, useTranslate } from "@refinedev/core";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { EmptyState } from "@/components/feedback/EmptyState";
import { PageError } from "@/components/feedback/PageError";
import { PageLoader } from "@/components/feedback/PageLoader";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import {
  createSource,
  deleteSource,
  getAccessSchema,
  getSourceAccess,
  listSources,
  patchSource,
  testSource,
  testSourceDraft,
} from "@/features/sources/api";
import { SourceSchedulesModal } from "@/features/schedules/SourceSchedulesModal";
import { SpecTree, defaultsFromSchema } from "@/features/sources/SpecTree";
import type {
  ConnectorSpec,
  Engine,
  Source,
  SourceAccess,
} from "@/features/sources/types";
import { ApiError } from "@/lib/api";

type IdentityForm = {
  key: string;
  name: string;
  description: string;
  status: "active" | "disabled";
  engine: Engine | "";
};

const ENGINE_OPTIONS = [
  { value: "postgresql", label: "PostgreSQL" },
  { value: "mssql", label: "MSSQL" },
  { value: "oracle", label: "Oracle" },
];

function emptyIdentity(engine: Engine = "postgresql"): IdentityForm {
  return {
    key: "",
    name: "",
    description: "",
    status: "active",
    engine,
  };
}

function scopeLabel(source: Source): string {
  const access = source.access;
  if (!access || typeof access !== "object") return "—";
  const database = access.database;
  const service = access.service_name;
  if (typeof database === "string" && database.trim()) return database;
  if (typeof service === "string" && service.trim()) return service;
  return "—";
}

export function SourceList() {
  const t = useTranslate();
  const { open } = useNotification();
  const { data: canWrite } = useCan({
    resource: ModuleId.sources,
    action: ModuleAction.create,
  });
  const { data: canRunJobs } = useCan({
    resource: ModuleId.jobs,
    action: ModuleAction.list,
  });
  const { data: canReadDiffs } = useCan({
    resource: ModuleId.sources,
    action: ModuleAction.show,
  });

  const [items, setItems] = useState<Source[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Source | null>(null);
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(false);
  const [schema, setSchema] = useState<ConnectorSpec | null>(null);
  const [access, setAccess] = useState<SourceAccess>({});

  const [enginePending, setEnginePending] = useState<Engine | null>(null);
  const [pendingDelete, setPendingDelete] = useState<Source | null>(null);
  const [deleting, setDeleting] = useState(false);
  const [scheduleSource, setScheduleSource] = useState<Source | null>(null);

  const showActions = Boolean(
    canWrite?.can || canRunJobs?.can || canReadDiffs?.can,
  );

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const srcs = await listSources();
      setItems(srcs.items);
    } catch (err) {
      setError(err instanceof ApiError ? err.detail : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const form = useForm<IdentityForm>({
    initialValues: emptyIdentity(),
    validate: {
      key: (v) =>
        editing ? null : v.trim() ? null : t("sources.validation.required"),
      name: (v) => (v.trim() ? null : t("sources.validation.required")),
      engine: (v) => (v ? null : t("sources.validation.required")),
    },
  });

  const loadSchemaAndDefaults = async (engine: Engine) => {
    const res = await getAccessSchema(engine);
    setSchema(res.schema);
    return defaultsFromSchema(res.schema);
  };

  const openCreate = async () => {
    setEditing(null);
    form.setValues(emptyIdentity("postgresql"));
    form.clearErrors();
    try {
      const defaults = await loadSchemaAndDefaults("postgresql");
      setAccess(defaults);
      setModalOpen(true);
    } catch (err) {
      open?.({
        type: "error",
        message: err instanceof ApiError ? err.detail : String(err),
      });
    }
  };

  const openEdit = async (source: Source) => {
    const engine =
      source.engine === "postgresql" ||
      source.engine === "mssql" ||
      source.engine === "oracle"
        ? source.engine
        : "postgresql";
    setEditing(source);
    form.setValues({
      key: source.key,
      name: source.name,
      description: source.description ?? "",
      status: source.status === "disabled" ? "disabled" : "active",
      engine,
    });
    form.clearErrors();
    try {
      const defaults = await loadSchemaAndDefaults(engine);
      try {
        const full = await getSourceAccess(source.id);
        setAccess(full.access);
      } catch (err) {
        // Missing/corrupt blob: open with schema defaults + projected non-secrets
        setAccess({ ...defaults, ...(source.access ?? {}) });
        open?.({
          type: "error",
          message:
            err instanceof ApiError
              ? err.detail
              : t("sources.access.reenterHint"),
        });
      }
      setModalOpen(true);
    } catch (err) {
      open?.({
        type: "error",
        message: err instanceof ApiError ? err.detail : String(err),
      });
    }
  };

  const applyEngine = async (next: Engine) => {
    form.setFieldValue("engine", next);
    setAccess(await loadSchemaAndDefaults(next));
  };

  const confirmEngineChange = (next: Engine | null) => {
    if (!next) {
      form.setFieldValue("engine", "");
      return;
    }
    const current = form.values.engine;
    if (current === next) return;
    if (!current) {
      void applyEngine(next);
      return;
    }
    setEnginePending(next);
  };

  const runProbe = async () => {
    const values = form.values;
    if (!values.engine) {
      form.setFieldError("engine", t("sources.validation.required"));
      return;
    }
    if (!String(access.password ?? "").trim()) {
      open?.({
        type: "error",
        message: t("sources.validation.secretForTest"),
      });
      return;
    }
    setTesting(true);
    try {
      const result = editing
        ? await testSource(editing.id, {
            engine: values.engine,
            access,
          })
        : await testSourceDraft({
            engine: values.engine,
            access,
          });
      if (result.ok) {
        open?.({ type: "success", message: t("sources.test.success") });
      } else {
        open?.({
          type: "error",
          message: result.message || t("sources.test.failed"),
        });
      }
    } catch (err) {
      open?.({
        type: "error",
        message: err instanceof ApiError ? err.detail : String(err),
      });
    } finally {
      setTesting(false);
    }
  };

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    setDeleting(true);
    try {
      await deleteSource(pendingDelete.id);
      open?.({
        type: "success",
        message: t("sources.delete.success"),
      });
      setPendingDelete(null);
      await load();
    } catch (err) {
      open?.({
        type: "error",
        message:
          err instanceof ApiError ? err.detail : t("sources.delete.error"),
      });
    } finally {
      setDeleting(false);
    }
  };

  const createAction = (
    <CanAccess resource={ModuleId.sources} action={ModuleAction.create}>
      <Button size="sm" onClick={() => void openCreate()}>
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
    <Stack gap="md">
      <Group justify="space-between" align="flex-start" wrap="wrap">
        <Stack gap={4} style={{ flex: 1, minWidth: 0 }}>
          <h2 className="m_8a5d1357 mantine-Title-root" data-order={2}>
            {t("sources.title")}
          </h2>
          <p className="m_b6d8b162 mantine-Text-root" data-size="sm">
            {t("sources.description")}
          </p>
        </Stack>
        {createAction}
      </Group>

      {items.length === 0 ? (
        <EmptyState message={t("sources.empty")} />
      ) : (
        <Table striped highlightOnHover withTableBorder>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t("sources.fields.key")}</Table.Th>
              <Table.Th>{t("sources.fields.name")}</Table.Th>
              <Table.Th>{t("sources.fields.engine")}</Table.Th>
              <Table.Th>{t("sources.fields.host")}</Table.Th>
              <Table.Th>{t("sources.fields.database")}</Table.Th>
              <Table.Th>{t("sources.fields.status")}</Table.Th>
              <Table.Th>{t("sources.fields.hasAccess")}</Table.Th>
              {showActions ? (
                <Table.Th>{t("sources.fields.actions")}</Table.Th>
              ) : null}
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {items.map((source) => (
              <Table.Tr key={source.id}>
                <Table.Td>{source.key}</Table.Td>
                <Table.Td>{source.name}</Table.Td>
                <Table.Td>{source.engine ?? "—"}</Table.Td>
                <Table.Td>
                  {typeof source.access?.host === "string"
                    ? source.access.host
                    : "—"}
                </Table.Td>
                <Table.Td>{scopeLabel(source)}</Table.Td>
                <Table.Td>
                  <Badge
                    color={source.status === "active" ? "green" : "gray"}
                    variant="light"
                  >
                    {source.status}
                  </Badge>
                </Table.Td>
                <Table.Td>
                  {source.has_access
                    ? t("sources.fields.hasAccessYes")
                    : t("sources.fields.hasAccessNo")}
                </Table.Td>
                {showActions ? (
                  <Table.Td>
                    <Group gap="xs" wrap="nowrap">
                      <CanAccess
                        resource={ModuleId.sources}
                        action={ModuleAction.show}
                      >
                        <Button
                          component={Link}
                          href={`/console/sources/${source.id}/structure-diffs`}
                          size="compact-xs"
                          variant="default"
                        >
                          {t("structureDiffs.open")}
                        </Button>
                      </CanAccess>
                      <CanAccess
                        resource={ModuleId.jobs}
                        action={ModuleAction.list}
                      >
                        <Button
                          size="compact-xs"
                          variant="light"
                          disabled={
                            source.kind !== "database" || !source.has_access
                          }
                          onClick={() => setScheduleSource(source)}
                        >
                          {t("schedules.related.open")}
                        </Button>
                      </CanAccess>
                      {canWrite?.can ? (
                        <>
                          <Button
                            size="compact-xs"
                            variant="light"
                            onClick={() => void openEdit(source)}
                          >
                            {t("sources.edit")}
                          </Button>
                          <Tooltip
                            label={t("sources.delete.disabledHint")}
                            disabled={source.status === "disabled"}
                          >
                            <span>
                              <Button
                                size="compact-xs"
                                variant="light"
                                color="red"
                                disabled={
                                  source.status !== "disabled" || deleting
                                }
                                onClick={() => setPendingDelete(source)}
                              >
                                {t("sources.delete")}
                              </Button>
                            </span>
                          </Tooltip>
                        </>
                      ) : null}
                    </Group>
                  </Table.Td>
                ) : null}
              </Table.Tr>
            ))}
          </Table.Tbody>
        </Table>
      )}

      <Modal.Stack>
        <Modal
          stackId="source-form"
          opened={modalOpen}
          onClose={() => setModalOpen(false)}
          title={editing ? t("sources.edit") : t("sources.create")}
          size="lg"
        >
          <form
            onSubmit={form.onSubmit(async (values) => {
              if (!values.engine) return;
              setBusy(true);
              try {
                if (editing) {
                  await patchSource(editing.id, {
                    name: values.name.trim(),
                    description: values.description.trim() || null,
                    status: values.status,
                    engine: values.engine,
                    access,
                  });
                  open?.({
                    type: "success",
                    message: t("sources.update.success"),
                  });
                } else {
                  await createSource({
                    key: values.key.trim(),
                    name: values.name.trim(),
                    kind: "database",
                    description: values.description.trim() || null,
                    engine: values.engine,
                    access,
                  });
                  open?.({
                    type: "success",
                    message: t("sources.create.success"),
                  });
                }
                setModalOpen(false);
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
            <Stack gap="sm">
              {!editing ? (
                <TextInput
                  label={t("sources.fields.key")}
                  required
                  {...form.getInputProps("key")}
                />
              ) : null}
              <TextInput
                label={t("sources.fields.name")}
                required
                {...form.getInputProps("name")}
              />
              <Textarea
                label={t("sources.fields.description")}
                autosize
                minRows={2}
                {...form.getInputProps("description")}
              />
              {editing ? (
                <Select
                  label={t("sources.fields.status")}
                  data={[
                    { value: "active", label: "active" },
                    { value: "disabled", label: "disabled" },
                  ]}
                  {...form.getInputProps("status")}
                />
              ) : null}
              <Select
                label={t("sources.fields.engine")}
                data={ENGINE_OPTIONS}
                required
                placeholder={t("sources.validation.required")}
                value={form.values.engine || null}
                onChange={(value) =>
                  confirmEngineChange((value as Engine | null) ?? null)
                }
              />

              <SpecTree
                schema={schema}
                value={access}
                onChange={setAccess}
                disabled={busy || testing}
              />

              <Group justify="space-between">
                <Button
                  type="button"
                  variant="default"
                  loading={testing}
                  disabled={busy}
                  onClick={() => void runProbe()}
                >
                  {t("sources.test")}
                </Button>
                <Group>
                  <Button
                    variant="default"
                    onClick={() => setModalOpen(false)}
                    disabled={busy || testing}
                  >
                    {t("common.cancel")}
                  </Button>
                  <Button type="submit" loading={busy} disabled={testing}>
                    {t("common.save")}
                  </Button>
                </Group>
              </Group>
            </Stack>
          </form>
        </Modal>

        <Modal
          stackId="engine-switch"
          opened={enginePending !== null}
          onClose={() => setEnginePending(null)}
          title={t("sources.engineSwitch.title")}
          size="sm"
        >
          <Stack gap="md">
            <Text size="sm">{t("sources.engineSwitch.body")}</Text>
            <Group justify="flex-end">
              <Button variant="default" onClick={() => setEnginePending(null)}>
                {t("common.cancel")}
              </Button>
              <Button
                onClick={() => {
                  const next = enginePending;
                  setEnginePending(null);
                  if (next) void applyEngine(next);
                }}
              >
                {t("sources.engineSwitch.confirm")}
              </Button>
            </Group>
          </Stack>
        </Modal>

        <Modal
          stackId="source-delete"
          opened={pendingDelete !== null}
          onClose={() => setPendingDelete(null)}
          title={t("sources.delete.confirmTitle")}
          size="sm"
        >
          <Stack gap="md">
            <Text size="sm">
              {pendingDelete
                ? t("sources.delete.confirmBody", { name: pendingDelete.name })
                : null}
            </Text>
            <Group justify="flex-end">
              <Button
                variant="default"
                onClick={() => setPendingDelete(null)}
                disabled={deleting}
              >
                {t("common.cancel")}
              </Button>
              <Button
                color="red"
                loading={deleting}
                onClick={() => void confirmDelete()}
              >
                {t("common.confirm")}
              </Button>
            </Group>
          </Stack>
        </Modal>
      </Modal.Stack>

      <SourceSchedulesModal
        sourceId={scheduleSource?.id ?? null}
        sourceLabel={
          scheduleSource
            ? `${scheduleSource.key} — ${scheduleSource.name}`
            : undefined
        }
        opened={scheduleSource !== null}
        onClose={() => setScheduleSource(null)}
      />
    </Stack>
  );
}
