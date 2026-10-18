"use client";

import { Button, Modal, Stack, Table } from "@mantine/core";
import { FormDialog } from "@/components/form/FormDialog";
import {
  FormErrorSummary,
  saveFailureFrom,
  type SaveFailure,
} from "@/components/form/FormErrorSummary";
import { useConsoleForm } from "@/components/form/useConsoleForm";
import { useCan, useNotification, useTranslate } from "@refinedev/core";
import { useCallback, useState } from "react";

import { CreateListAction } from "@/components/access/CreateListAction";
import { StatusBadge } from "@/components/display/StatusBadge";
import { presentSourceStatus } from "@/components/display/statusTone";
import { SelectField } from "@/components/form/SelectField";
import { TextareaField } from "@/components/form/TextareaField";
import { TextField } from "@/components/form/TextField";
import { ListTable } from "@/components/display/ListTable";
import { ListToolbar } from "@/components/display/ListToolbar";
import { RecordReference } from "@/components/display/RecordReference";
import { RowActions } from "@/components/display/RowActions";
import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import { useConsoleNavigation } from "@/components/navigation/useConsoleNavigation";
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
import { engineLabel } from "@/features/sources/engineLabel";
import { SpecTree, defaultsFromSchema } from "@/features/sources/SpecTree";
import type {
  ConnectorSpec,
  Engine,
  Source,
  SourceAccess,
} from "@/features/sources/types";
import { useConfirmAction } from "@/hooks/useConfirmAction";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { useListQuery } from "@/hooks/useListQuery";
import { problemMessage } from "@/lib/problem";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 100;

type IdentityForm = {
  key: string;
  name: string;
  description: string;
  status: "active" | "disabled";
  engine: Engine | "";
};

const ENGINES = ["postgresql", "mssql", "oracle"] as const;

function selectedEngine(value: string): Engine | undefined {
  return ENGINES.find((engine) => engine === value);
}

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
  const { push } = useConsoleNavigation();
  const engineOptions = ENGINES.map((value) => ({
    value,
    label: engineLabel(t, value),
  }));
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
  const [saveFailure, setSaveFailure] = useState<SaveFailure | null>(null);
  const [testing, setTesting] = useState(false);
  const [schema, setSchema] = useState<ConnectorSpec | null>(null);
  const [access, setAccess] = useState<SourceAccess>({});

  const engineConfirm = useConfirmAction<Engine>();
  const query = useListQuery({
    filters: [{ key: "engine", type: "select", defaultValue: "" }],
  });
  const engine = query.select("engine");

  const showActions = Boolean(
    canWrite?.can || canRunJobs?.can || canReadDiffs?.can,
  );

  const fetchPage = useCallback(
    (page: PageQuery) =>
      listSources({
        ...page,
        q: query.search || undefined,
        engine: selectedEngine(engine),
      }),
    [query.search, engine],
  );
  const list = useConsolePagedList({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
    resetDeps: [query.search, engine],
    filtered: query.isFiltered,
    page: query.page,
    onPageChange: query.setPage,
  });
  const { items, reload } = list;

  const form = useConsoleForm<IdentityForm>({
    initialValues: emptyIdentity(),
    onValuesChange: () => setSaveFailure(null),
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
    form.markSaved();
    form.clearErrors();
    setSaveFailure(null);
    try {
      const defaults = await loadSchemaAndDefaults("postgresql");
      setAccess(defaults);
      setModalOpen(true);
    } catch (err) {
      open?.({
        type: "error",
        message: problemMessage(t, err, String(err)),
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
    form.markSaved();
    form.clearErrors();
    setSaveFailure(null);
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
            problemMessage(t, err, t("sources.access.reenterHint")),
        });
      }
      setModalOpen(true);
    } catch (err) {
      open?.({
        type: "error",
        message: problemMessage(t, err, String(err)),
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
        message: problemMessage(t, err, String(err)),
      });
    } finally {
      setTesting(false);
    }
  };

  const closeModal = () => {
    setModalOpen(false);
    setSaveFailure(null);
    form.reset();
  };

  const saveSource = async (values: IdentityForm) => {
    if (!values.engine) return;
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
      form.markSaved();
      setSaveFailure(null);
      setModalOpen(false);
      await reload();
    } catch (err) {
      setSaveFailure(
        saveFailureFrom(t, err, form.applyApiError(err), String(err)),
      );
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
      toolbar={
        <ListToolbar
          query={query}
          searchPlaceholder={t("sources.search")}
          filters={[
            {
              key: "engine",
              label: t("sources.fields.engine"),
              options: engineOptions,
            },
          ]}
        />
      }
    >
      <ListTable
        list={list}
        columnCount={showActions ? 7 : 6}
        emptyMessage={t("sources.empty")}
        emptyAction={createAction}
        noMatchMessage={t("sources.list.noMatch")}
        onClearFilters={query.clear}
        head={
          <Table.Tr>
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
            <Table.Td>
              <RecordReference
                name={source.name}
                recordKey={source.key}
                href={
                  canReadDiffs?.can
                    ? `/console/sources/${source.id}/structure-diffs`
                    : undefined
                }
              />
            </Table.Td>
            <Table.Td>{source.engine ? engineLabel(t, source.engine) : "—"}</Table.Td>
            <Table.Td>
              {typeof source.access?.host === "string"
                ? source.access.host
                : "—"}
            </Table.Td>
            <Table.Td>{scopeLabel(source)}</Table.Td>
            <Table.Td>
              <StatusBadge
                tone={presentSourceStatus(source.status).tone}
                labelKey={presentSourceStatus(source.status).labelKey}
              />
            </Table.Td>
            <Table.Td>
              {source.has_access
                ? t("sources.fields.hasAccessYes")
                : t("sources.fields.hasAccessNo")}
            </Table.Td>
            {showActions ? (
              <Table.Td>
                <RowActions
                  recordName={source.name}
                  verbs={[
                    {
                      key: "diffs",
                      label: t("structureDiffs.open"),
                      hidden: !canReadDiffs?.can,
                      safety: "immediate",
                      onClick: () =>
                        push(`/console/sources/${source.id}/structure-diffs`),
                    },
                    {
                      key: "schedules",
                      label: t("schedules.related.open"),
                      hidden: !canRunJobs?.can,
                      safety: "immediate",
                      onClick: () =>
                        push(`/console/sources/${source.id}/schedules`),
                    },
                    {
                      key: "edit",
                      label: t("sources.edit"),
                      hidden: !canWrite?.can,
                      safety: "immediate",
                      onClick: () => void openEdit(source),
                    },
                    {
                      key: "delete",
                      label: t("sources.delete"),
                      color: "red",
                      hidden: !canWrite?.can,
                      disabledReason:
                        source.status === "disabled"
                          ? undefined
                          : t("sources.delete.disabledHint"),
                      action: {
                        safety: "confirm",
                        recordName: source.name,
                        title: t("sources.delete.confirmTitle"),
                        consequence: t("sources.delete.consequence"),
                        confirmLabel: t("sources.delete"),
                        confirmColor: "red",
                        outcome: t("sources.delete.success"),
                        execute: () => deleteSource(source.id),
                        onSuccess: () => reload(),
                      },
                    },
                  ]}
                />
              </Table.Td>
            ) : null}
          </Table.Tr>
        ))}
      </ListTable>

      <FormDialog
        opened={modalOpen}
        onClose={closeModal}
        title={editing ? t("sources.edit") : t("sources.create")}
        size="lg"
        dirty={form.dirty}
        submitting={form.submitting}
        submitLabel={t("common.save")}
        summary={<FormErrorSummary failure={saveFailure} />}
        onSubmit={() => void form.submit(saveSource)}
        leading={
          <Button
            type="button"
            variant="default"
            loading={testing}
            disabled={form.submitting}
            onClick={() => void runProbe()}
          >
            {t("sources.test")}
          </Button>
        }
      >
        <Stack gap="sm">
          {!editing ? (
            <TextField
              label={t("sources.fields.key")}
              required
              editable
              {...form.fieldProps("key")}
            />
          ) : null}
          <TextField
            label={t("sources.fields.name")}
            required
            editable
            {...form.fieldProps("name")}
          />
          <TextareaField
            label={t("sources.fields.description")}
            autosize
            minRows={2}
            editable
            {...form.fieldProps("description")}
          />
          {editing ? (
            <SelectField
              label={t("sources.fields.status")}
              editable
              data={[
                { value: "active", label: t("sources.status.active") },
                { value: "disabled", label: t("sources.status.disabled") },
              ]}
              {...form.fieldProps("status")}
            />
          ) : null}
          <SelectField
            label={t("sources.fields.engine")}
            data={engineOptions}
            required
            editable
            placeholder={t("sources.validation.required")}
            {...form.fieldProps("engine")}
            value={form.values.engine || null}
            onChange={(value) =>
              confirmEngineChange((value as Engine | null) ?? null)
            }
          />
          <SpecTree
            schema={schema}
            value={access}
            onChange={setAccess}
            editable
          />
        </Stack>
      </FormDialog>

      <Modal.Stack>
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

      </Modal.Stack>
    </PageChrome>
  );
}
