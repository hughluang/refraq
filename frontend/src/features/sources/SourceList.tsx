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
import { useCallback, useState } from "react";

import { CreateListAction } from "@/components/access/CreateListAction";
import { ListTable } from "@/components/display/ListTable";
import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import { PageChrome } from "@/components/layout/PageChrome";
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
} from "@/features/sources/api/sources";
import { SpecTree, defaultsFromSchema } from "@/features/sources/SpecTree";
import type {
  ConnectorSpec,
  Engine,
  Source,
  SourceAccess,
} from "@/features/sources/types";
import { useConfirmAction } from "@/hooks/useConfirmAction";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { ApiError } from "@/lib/api";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 100;

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

  const [modalOpen, setModalOpen] = useState(false);
  const [editing, setEditing] = useState<Source | null>(null);
  const [busy, setBusy] = useState(false);
  const [testing, setTesting] = useState(false);
  const [schema, setSchema] = useState<ConnectorSpec | null>(null);
  const [access, setAccess] = useState<SourceAccess>({});

  const engineConfirm = useConfirmAction<Engine>();
  const deleteConfirm = useConfirmAction<Source>();
  const [deleting, setDeleting] = useState(false);

  const showActions = Boolean(
    canWrite?.can || canRunJobs?.can || canReadDiffs?.can,
  );

  const fetchPage = useCallback(
    (query: PageQuery) => listSources(query),
    [],
  );
  const list = useConsolePagedList({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
  });
  const { items, reload } = list;

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
    engineConfirm.open(next);
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
    const pending = deleteConfirm.pending;
    if (!pending) return;
    setDeleting(true);
    try {
      await deleteSource(pending.id);
      open?.({
        type: "success",
        message: t("sources.delete.success"),
      });
      deleteConfirm.close();
      await reload();
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
    <CreateListAction
      resource={ModuleId.sources}
      onClick={() => void openCreate()}
    >
      {t("sources.create")}
    </CreateListAction>
  );

  return (
    <PageChrome
      title={t("sources.title")}
      description={t("sources.description")}
      actions={createAction}
    >
      <ListTable
        list={list}
        columnCount={showActions ? 8 : 7}
        emptyMessage={t("sources.empty")}
        head={
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
        }
      >
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
                      component={Link}
                      href={`/console/sources/${source.id}/schedules`}
                      size="compact-xs"
                      variant="light"
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
                            onClick={() => deleteConfirm.open(source)}
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
      </ListTable>

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
                  const updated = await patchSource(editing.id, {
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
                  if (updated.schedules && updated.schedules.length > 0) {
                    open?.({
                      type: "success",
                      message: t("schedules.seededOnSourceUpdate"),
                    });
                  }
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
                await reload();
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

        <ConfirmActionModal
          stackId="engine-switch"
          opened={engineConfirm.opened}
          onClose={engineConfirm.close}
          title={t("sources.engineSwitch.title")}
          body={t("sources.engineSwitch.body")}
          confirmLabel={t("sources.engineSwitch.confirm")}
          size="sm"
          onConfirm={() => {
            const next = engineConfirm.pending;
            engineConfirm.close();
            if (next) void applyEngine(next);
          }}
        />

        <ConfirmActionModal
          stackId="source-delete"
          opened={deleteConfirm.opened}
          onClose={deleteConfirm.close}
          title={t("sources.delete.confirmTitle")}
          body={
            deleteConfirm.pending
              ? t("sources.delete.confirmBody", {
                  name: deleteConfirm.pending.name,
                })
              : null
          }
          confirmColor="red"
          loading={deleting}
          size="sm"
          onConfirm={() => void confirmDelete()}
        />
      </Modal.Stack>
    </PageChrome>
  );
}
