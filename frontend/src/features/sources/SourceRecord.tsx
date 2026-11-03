"use client";

import { Box, Button, Modal, Stack, Tooltip } from "@mantine/core";
import { useCan, useNotification, usePermissions, useTranslate } from "@refinedev/core";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { presentSaveFailure } from "@/components/feedback/presentSaveFailure";
import { SelectField } from "@/components/form/SelectField";
import { TextareaField } from "@/components/form/TextareaField";
import { TextField } from "@/components/form/TextField";
import { useConsoleForm, type UseConsoleFormReturn } from "@/components/form/useConsoleForm";
import { HeaderAction, HeaderActions } from "@/components/layout/HeaderActions";
import { PageChrome } from "@/components/layout/PageChrome";
import { PageTabs, useConsoleTab } from "@/components/layout/consoleTabs";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { suppressLeaveGuard } from "@/components/navigation/leaveGuard";
import { useConsoleNavigation } from "@/components/navigation/useConsoleNavigation";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import {
  changeSourceMembership,
  createSourceMembership,
  deleteSourceMembership,
  listSourceMemberships,
} from "@/features/sources/api/memberships";
import {
  createSource,
  deleteSource,
  getAccessSchema,
  getSource,
  getSourceAccess,
  listSources,
  patchSource,
  testSource,
  testSourceDraft,
} from "@/features/sources/api/sources";
import { MembershipCollection } from "@/features/sources/MembershipCollection";
import {
  SOURCE_ACCESS_MANAGE,
  SOURCE_READ,
  type MembershipWrite,
} from "@/features/sources/membership";
import { engineLabel, selectedEngine, SOURCE_ENGINES } from "@/features/sources/engineLabel";
import {
  SOURCE_DIFFS_TAB,
  SOURCE_MEMBERS_TAB,
  SOURCE_RECORD_TAB,
  sourceEditPath,
  sourceShowPath,
} from "@/features/sources/sourceRecordTab";
import { SpecTree, defaultsFromSchema } from "@/features/sources/SpecTree";
import { StructureDiffList } from "@/features/sources/structure-diffs/StructureDiffList";
import type {
  ConnectorSpec,
  Engine,
  Source,
  SourceAccess,
} from "@/features/sources/types";
import { useConfirmAction } from "@/hooks/useConfirmAction";
import { ApiError } from "@/lib/api";
import { problemMessage } from "@/lib/problem";

const FORM_ID = "source-record-form";
const DEFAULT_ENGINE: Engine = "postgresql";

type Values = {
  key: string;
  name: string;
  description: string;
  status: "active" | "disabled";
  engine: Engine | "";
  access: SourceAccess;
};

type Props = { mode: "create" } | { mode: "show" | "edit"; sourceId: string };

const EMPTY: Values = {
  key: "",
  name: "",
  description: "",
  status: "active",
  engine: "",
  access: {},
};

function formEngine(engine: string | null | undefined): Engine {
  return selectedEngine(engine ?? "") ?? DEFAULT_ENGINE;
}

function valuesFrom(source: Source, access: SourceAccess): Values {
  return {
    key: source.key,
    name: source.name,
    description: source.description ?? "",
    status: source.status === "disabled" ? "disabled" : "active",
    engine: formEngine(source.engine),
    access,
  };
}

async function applyEngine(
  next: Engine,
  form: UseConsoleFormReturn<Values>,
  setSchema: (schema: ConnectorSpec | null) => void,
  t: (key: string) => string,
): Promise<void> {
  try {
    const res = await getAccessSchema(next);
    setSchema(res.schema);
    form.setFieldValue("engine", next);
    form.setFieldValue("access", defaultsFromSchema(res.schema));
  } catch (err) {
    presentProblemNotification(t, err);
  }
}

export function SourceRecord(props: Props) {
  if (props.mode === "create") return <SourceCreate />;
  return <SourceExisting mode={props.mode} sourceId={props.sourceId} />;
}

function SourceCreate() {
  const t = useTranslate();
  const { open } = useNotification();
  const [schema, setSchema] = useState<ConnectorSpec | null>(null);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const [testing, setTesting] = useState(false);
  const engineConfirm = useConfirmAction<Engine>();
  const form = useConsoleForm<Values>({
    initialValues: EMPTY,
    validate: {
      key: (value) => (value.trim() ? null : t("sources.validation.required")),
      name: (value) => (value.trim() ? null : t("sources.validation.required")),
      engine: (value) => (value ? null : t("sources.validation.required")),
    },
  });

  useEffect(() => {
    let cancelled = false;
    setReady(false);
    setFailed(false);
    void getAccessSchema(DEFAULT_ENGINE)
      .then((res) => {
        if (cancelled) return;
        setSchema(res.schema);
        form.setValues({
          ...EMPTY,
          engine: DEFAULT_ENGINE,
          access: defaultsFromSchema(res.schema),
        });
        form.markSaved();
        setReady(true);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setFailed(true);
        presentProblemNotification(t, err, { onRetry: () => setAttempt((value) => value + 1) });
      });
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  if (!ready) {
    return (
      <PageChrome
        title={t("sources.create")}
        status={failed ? "unloaded" : "loading"}
        onRetry={failed ? () => setAttempt((value) => value + 1) : undefined}
      />
    );
  }

  return (
    <PageChrome
      title={t("sources.create")}
      actions={
        <HeaderActions
          standard={
            <>
              <Button component={ConsoleLink} href="/console/sources" variant="default" size="sm">
                {t("common.cancel")}
              </Button>
              <HeaderAction primary>
                <Button type="submit" form={FORM_ID} size="sm" loading={form.submitting}>
                  {t("common.save")}
                </Button>
              </HeaderAction>
            </>
          }
        />
      }
    >
      <form
        id={FORM_ID}
        noValidate
        onSubmit={form.onSubmit((values) => {
          const engine = selectedEngine(values.engine);
          if (!engine) return;
          return createSource({
            key: values.key.trim(),
            name: values.name.trim(),
            kind: "database",
            description: values.description.trim() || null,
            engine,
            access: values.access,
          })
            .then((created) => {
              form.markSaved();
              suppressLeaveGuard();
              open?.({ type: "success", message: t("sources.create.success") });
              window.location.replace(sourceEditPath(created.source.id));
            })
            .catch((err: unknown) => {
              presentSaveFailure(t, err, form.applyApiError);
            });
        })}
      >
        <SourceFields
          form={form}
          schema={schema}
          mode="create"
          editable
          testing={testing}
          onEngineChange={(next) =>
            confirmEngine(
              form.values.engine,
              next,
              engineConfirm.open,
              (engine) => applyEngine(engine, form, setSchema, t),
              form.setFieldValue,
            )
          }
          onTest={() =>
            void runProbe(form.values, null, t, open, form.setFieldError, setTesting)
          }
        />
      </form>
      <EngineSwitchDialog
        confirm={engineConfirm}
        onApply={(next) => void applyEngine(next, form, setSchema, t)}
      />
    </PageChrome>
  );
}

function SourceExisting({
  mode,
  sourceId,
}: {
  mode: "show" | "edit";
  sourceId: string;
}) {
  const t = useTranslate();
  const { replace } = useConsoleNavigation();
  const { open } = useNotification();
  const { data: canWrite } = useCan({
    resource: ModuleId.sources,
    action: ModuleAction.edit,
  });
  const { data: canDelete } = useCan({
    resource: ModuleId.sources,
    action: ModuleAction.delete,
  });
  const { data: permissions, isLoading: permissionsLoading } = usePermissions<string[]>({});
  const held = permissions ?? [];
  const canReadSources = held.includes(SOURCE_READ);
  const canManageAccess = held.includes(SOURCE_ACCESS_MANAGE);
  const writeReady = mode !== "edit" || canWrite?.can === true;
  const [schema, setSchema] = useState<ConnectorSpec | null>(null);
  const [record, setRecord] = useState<Source | null>(null);
  const [identityOnly, setIdentityOnly] = useState(false);
  const [missing, setMissing] = useState(false);
  const [membersAllowed, setMembersAllowed] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadFailed, setLoadFailed] = useState(false);
  const [testing, setTesting] = useState(false);
  const [reloadKey, setReloadKey] = useState(0);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const showMembers = canManageAccess || membersAllowed;
  const tabItems = [
    { value: SOURCE_RECORD_TAB },
    ...(identityOnly ? [] : [{ value: SOURCE_DIFFS_TAB }]),
    ...(showMembers ? [{ value: SOURCE_MEMBERS_TAB }] : []),
  ];
  const consoleTab = useConsoleTab(tabItems);
  const tab = consoleTab.value;
  const engineConfirm = useConfirmAction<Engine>();
  const form = useConsoleForm<Values>({
    initialValues: EMPTY,
    validate: {
      name: (value) => (value.trim() ? null : t("sources.validation.required")),
      engine: (value) => (value ? null : t("sources.validation.required")),
    },
  });

  const formRef = useRef(form);
  formRef.current = form;
  const openRef = useRef(open);
  openRef.current = open;
  const tRef = useRef(t);
  tRef.current = t;

  const load = useCallback(
    async (silent = false) => {
      if (mode === "edit" && !writeReady) return;
      if (permissionsLoading || permissions == null) return;
      const translate = tRef.current;
      const notify = openRef.current;
      const currentForm = formRef.current;
      if (!silent) {
        setLoading(true);
        setLoadFailed(false);
        setMissing(false);
      }
      const showIdentity = (source: Source) => {
        const engine = selectedEngine(source.engine ?? "") ?? "";
        currentForm.setValues({
          ...EMPTY,
          key: source.key,
          name: source.name,
          status: source.status === "disabled" ? "disabled" : "active",
          engine,
        });
        currentForm.markSaved();
        setSchema(null);
        setRecord({
          id: source.id,
          key: source.key,
          name: source.name,
          kind: source.kind,
          status: source.status,
          engine: source.engine,
        });
        setIdentityOnly(true);
        setMissing(false);
        setLoadFailed(false);
        setMembersAllowed(true);
      };
      try {
        const source = await loadVisibleSource(sourceId, canReadSources, canManageAccess);
        if (source == null) {
          setRecord(null);
          setMissing(true);
          setLoadFailed(false);
          return;
        }
        if (source.identityOnly) {
          showIdentity(source.source);
          return;
        }
        const loaded = source.source;
        const engine = formEngine(loaded.engine);
        const schemaRes = await getAccessSchema(engine);
        let access: SourceAccess = { ...(loaded.access ?? {}) };
        if (mode === "edit") {
          try {
            const full = await getSourceAccess(sourceId);
            access = full.access;
          } catch (err) {
            access = { ...defaultsFromSchema(schemaRes.schema), ...access };
            notify?.({
              type: "error",
              message: problemMessage(translate, err, translate("sources.access.reenterHint")),
            });
          }
        }
        const allowMembers = await canListMembers(sourceId, canManageAccess);
        setSchema(schemaRes.schema);
        currentForm.setValues(valuesFrom(loaded, access));
        currentForm.markSaved();
        setRecord(loaded);
        setIdentityOnly(false);
        setMissing(false);
        setLoadFailed(false);
        setMembersAllowed(allowMembers);
      } catch (err) {
        if (!silent) setLoadFailed(true);
        presentProblemNotification(translate, err, { onRetry: () => void load(false) });
      } finally {
        if (!silent) setLoading(false);
      }
    },
    [canManageAccess, canReadSources, mode, permissions, permissionsLoading, sourceId, writeReady],
  );

  useEffect(() => {
    void load(false);
  }, [load]);

  const memberClient = useMemo(
    () => ({
      list: () => listSourceMemberships(sourceId),
      create: (body: MembershipWrite) => createSourceMembership(sourceId, body),
      change: (membershipId: string, level: string) =>
        changeSourceMembership(sourceId, membershipId, level),
      remove: (membershipId: string) => deleteSourceMembership(sourceId, membershipId),
    }),
    [sourceId],
  );

  useEffect(() => {
    if (mode === "edit" && canWrite?.can === false) {
      replace(sourceShowPath(sourceId, tab));
    }
  }, [canWrite?.can, mode, replace, sourceId, tab]);

  if (mode === "edit" && canWrite?.can !== true) {
    return <PageChrome title={t("sources.title")} status="loading" />;
  }

  if (loading || !record) {
    return (
      <PageChrome
        title={t("sources.title")}
        status={missing ? "notFound" : loadFailed ? "unloaded" : "loading"}
        onRetry={loadFailed ? () => void load(false) : undefined}
      />
    );
  }

  const editable = mode === "edit" && !identityOnly;
  const save = async (values: Values) => {
    const engine = selectedEngine(values.engine);
    if (!engine) return;
    try {
      const updated = await patchSource(sourceId, {
        name: values.name.trim(),
        description: values.description.trim() || null,
        status: values.status,
        engine,
        access: values.access,
      });
      setRecord(updated.source);
      form.setValues(valuesFrom(updated.source, values.access));
      form.markSaved();
      open?.({ type: "success", message: t("sources.update.success") });
      if (updated.schedules && updated.schedules.length > 0) {
        open?.({ type: "success", message: t("schedules.seededOnSourceUpdate") });
      }
    } catch (err) {
      presentSaveFailure(t, err, form.applyApiError);
    }
  };

  const fields = (
    <SourceFields
      form={form}
      schema={schema}
      mode={mode}
      editable={editable}
      identityOnly={identityOnly}
      testing={testing}
      onEngineChange={(next) =>
        confirmEngine(
          form.values.engine,
          next,
          engineConfirm.open,
          (engine) => applyEngine(engine, form, setSchema, t),
          form.setFieldValue,
        )
      }
      onTest={() => void runProbe(form.values, sourceId, t, open, form.setFieldError, setTesting)}
    />
  );

  return (
    <PageTabs
      tabs={[
        { value: SOURCE_RECORD_TAB, label: t("sources.tabs.record"), panel: null },
        ...(identityOnly
          ? []
          : [{ value: SOURCE_DIFFS_TAB, label: t("structureDiffs.title"), panel: null }]),
        ...(showMembers
          ? [{ value: SOURCE_MEMBERS_TAB, label: t("sources.tabs.members"), panel: null }]
          : []),
      ]}
      value={tab}
      onChange={consoleTab.setTab}
    >
      {({ list }) => (
        <PageChrome
          title={t("sources.title")}
          recordTitle={record.name}
          recent={{ moduleId: "sources", title: record.name }}
          actions={
            <HeaderActions
              navigation={
                <>
                  <Button
                    component={ConsoleLink}
                    href="/console/sources"
                    variant="default"
                    size="sm"
                  >
                    {t("structureDiffs.backToSources")}
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="light"
                    onClick={() => {
                      setReloadKey((value) => value + 1);
                      void load(true);
                    }}
                  >
                    {t("jobs.refresh")}
                  </Button>
                </>
              }
              standard={recordStandard({
                mode: identityOnly ? "show" : mode,
                canWrite: Boolean(canWrite?.can) && !identityOnly,
                canDelete: Boolean(canDelete?.can),
                deletable: record.status === "disabled",
                submitting: form.submitting,
                sourceId,
                tab,
                onDelete: () => setConfirmDelete(true),
                editLabel: t("sources.edit"),
                cancelLabel: t("common.cancel"),
                saveLabel: t("common.save"),
                deleteLabel: t("sources.delete"),
                deleteHint: t("sources.delete.disabledHint"),
              })}
            />
          }
          tabs={list}
        >
          <div hidden={tab !== SOURCE_RECORD_TAB}>
            {editable ? (
              <form id={FORM_ID} noValidate onSubmit={form.onSubmit((values) => save(values))}>
                {fields}
              </form>
            ) : (
              fields
            )}
          </div>
          {tab === SOURCE_DIFFS_TAB && !identityOnly ? (
            <StructureDiffList key={reloadKey} sourceId={sourceId} />
          ) : null}
          {tab === SOURCE_MEMBERS_TAB && showMembers ? (
            <MembershipCollection client={memberClient} editable={canManageAccess} />
          ) : null}
          <EngineSwitchDialog
            confirm={engineConfirm}
            onApply={(next) => void applyEngine(next, form, setSchema, t)}
          />
          <ConfirmActionModal
            opened={confirmDelete}
            onClose={() => setConfirmDelete(false)}
            title={t("sources.delete.confirmTitle")}
            body={t("sources.delete.consequence")}
            confirmLabel={t("sources.delete")}
            confirmColor="red"
            loading={deleting}
            onConfirm={() => {
              setDeleting(true);
              void deleteSource(sourceId)
                .then(() => {
                  suppressLeaveGuard();
                  open?.({ type: "success", message: t("sources.delete.success") });
                  window.location.assign("/console/sources");
                })
                .catch((err: unknown) => {
                  setDeleting(false);
                  setConfirmDelete(false);
                  presentProblemNotification(t, err);
                });
            }}
          />
        </PageChrome>
      )}
    </PageTabs>
  );
}

function recordStandard({
  mode,
  canWrite,
  canDelete,
  deletable,
  submitting,
  sourceId,
  tab,
  onDelete,
  editLabel,
  cancelLabel,
  saveLabel,
  deleteLabel,
  deleteHint,
}: {
  mode: "show" | "edit";
  canWrite: boolean;
  canDelete: boolean;
  deletable: boolean;
  submitting: boolean;
  sourceId: string;
  tab: string;
  onDelete: () => void;
  editLabel: string;
  cancelLabel: string;
  saveLabel: string;
  deleteLabel: string;
  deleteHint: string;
}): ReactNode {
  const edit =
    mode === "show" && canWrite ? (
      <Button component={ConsoleLink} href={sourceEditPath(sourceId, tab)} size="sm" variant="light">
        {editLabel}
      </Button>
    ) : null;
  const authoring =
    mode === "edit" ? (
      <>
        <Button
          component={ConsoleLink}
          href={sourceShowPath(sourceId, tab)}
          variant="default"
          size="sm"
        >
          {cancelLabel}
        </Button>
        <HeaderAction primary>
          <Button type="submit" form={FORM_ID} size="sm" loading={submitting}>
            {saveLabel}
          </Button>
        </HeaderAction>
      </>
    ) : null;
  const remove = canDelete ? (
    <Tooltip label={deleteHint} disabled={deletable}>
      <Box component="span" style={{ display: "inline-flex" }}>
        <Button
          type="button"
          size="sm"
          variant="light"
          color="red"
          disabled={!deletable}
          onClick={onDelete}
        >
          {deleteLabel}
        </Button>
      </Box>
    </Tooltip>
  ) : null;
  if (edit == null && authoring == null && remove == null) return null;
  return (
    <>
      {edit}
      {authoring}
      {remove}
    </>
  );
}

function SourceFields({
  form,
  schema,
  mode,
  editable,
  identityOnly = false,
  testing,
  onEngineChange,
  onTest,
}: {
  form: ReturnType<typeof useConsoleForm<Values>>;
  schema: ConnectorSpec | null;
  mode: "create" | "show" | "edit";
  editable: boolean;
  identityOnly?: boolean;
  testing: boolean;
  onEngineChange: (next: Engine | null) => void;
  onTest: () => void;
}) {
  const t = useTranslate();
  const engineOptions = SOURCE_ENGINES.map((value) => ({
    value,
    label: engineLabel(t, value),
  }));
  const statusOptions = [
    { value: "active", label: t("sources.status.active") },
    { value: "disabled", label: t("sources.status.disabled") },
  ];
  return (
    <Stack gap="sm">
      <TextField
        label={t("sources.fields.key")}
        required={mode === "create"}
        editable={mode === "create"}
        {...form.fieldProps("key")}
      />
      <TextField
        label={t("sources.fields.name")}
        required={editable}
        editable={editable}
        {...form.fieldProps("name")}
      />
      {identityOnly ? null : (
        <TextareaField
          label={t("sources.fields.description")}
          autosize
          minRows={2}
          editable={editable}
          {...form.fieldProps("description")}
        />
      )}
      {mode === "create" ? null : (
        <SelectField
          label={t("sources.fields.status")}
          data={statusOptions}
          editable={editable}
          {...form.fieldProps("status")}
        />
      )}
      <SelectField
        label={t("sources.fields.engine")}
        data={engineOptions}
        required={editable}
        editable={editable}
        placeholder={t("sources.validation.required")}
        {...form.fieldProps("engine")}
        value={form.values.engine || null}
        onChange={(value) => onEngineChange((value as Engine | null) ?? null)}
      />
      {identityOnly ? null : (
        <SpecTree
          schema={schema}
          value={form.values.access}
          onChange={(next) => form.setFieldValue("access", next)}
          editable={editable}
        />
      )}
      {editable && !identityOnly ? (
        <Button
          type="button"
          variant="default"
          size="sm"
          loading={testing}
          disabled={form.submitting}
          onClick={onTest}
        >
          {t("sources.test")}
        </Button>
      ) : null}
    </Stack>
  );
}

function EngineSwitchDialog({
  confirm,
  onApply,
}: {
  confirm: ReturnType<typeof useConfirmAction<Engine>>;
  onApply: (engine: Engine) => void;
}) {
  const t = useTranslate();
  return (
    <Modal.Stack>
      <ConfirmActionModal
        stackId="engine-switch"
        opened={confirm.opened}
        onClose={confirm.close}
        title={t("sources.engineSwitch.title")}
        body={t("sources.engineSwitch.body")}
        confirmLabel={t("sources.engineSwitch.confirm")}
        size="sm"
        onConfirm={() => {
          const next = confirm.pending;
          confirm.close();
          if (next) onApply(next);
        }}
      />
    </Modal.Stack>
  );
}

type LoadedSource =
  | { identityOnly: false; source: Source }
  | { identityOnly: true; source: Source };

async function loadVisibleSource(
  sourceId: string,
  canReadSources: boolean,
  canManageAccess: boolean,
): Promise<LoadedSource | null> {
  if (canReadSources) {
    try {
      const body = await getSource(sourceId);
      return { identityOnly: false, source: body.source };
    } catch (err) {
      if (canManageAccess && isAbsentOrForbidden(err)) {
        const listed = await findListedSource(sourceId);
        if (listed) return { identityOnly: true, source: listed };
      }
      if (isSourceAbsent(err)) return null;
      throw err;
    }
  }
  if (canManageAccess) {
    const listed = await findListedSource(sourceId);
    return listed ? { identityOnly: true, source: listed } : null;
  }
  const body = await getSource(sourceId);
  return { identityOnly: false, source: body.source };
}

function isAbsentOrForbidden(err: unknown): boolean {
  return err instanceof ApiError && (err.status === 403 || err.status === 404);
}

function isSourceAbsent(err: unknown): boolean {
  return err instanceof ApiError && err.status === 404 && err.code === "SOURCE_NOT_FOUND";
}

async function canListMembers(sourceId: string, canManageAccess: boolean): Promise<boolean> {
  if (canManageAccess) return true;
  try {
    await listSourceMemberships(sourceId);
    return true;
  } catch (err) {
    if (isAbsentOrForbidden(err)) return false;
    throw err;
  }
}

async function findListedSource(sourceId: string): Promise<Source | null> {
  const limit = 100;
  let offset = 0;
  let total = Number.POSITIVE_INFINITY;
  while (offset < total) {
    const page = await listSources({ limit, offset });
    const found = page.items.find((item) => item.id === sourceId);
    if (found) return found;
    total = page.total;
    if (page.items.length === 0) return null;
    offset += page.items.length;
  }
  return null;
}

function confirmEngine(
  current: Engine | "",
  next: Engine | null,
  open: (engine: Engine) => void,
  apply: (engine: Engine) => Promise<void>,
  clearEngine: (field: "engine", value: "") => void,
) {
  if (!next) {
    clearEngine("engine", "");
    return;
  }
  if (current === next) return;
  if (!current) {
    void apply(next);
    return;
  }
  open(next);
}

async function runProbe(
  values: Values,
  editingId: string | null,
  t: (key: string) => string,
  open: ReturnType<typeof useNotification>["open"],
  setFieldError: (field: "engine", error: string) => void,
  setTesting: (testing: boolean) => void,
) {
  if (!values.engine) {
    setFieldError("engine", t("sources.validation.required"));
    return;
  }
  if (!String(values.access.password ?? "").trim()) {
    open?.({ type: "error", message: t("sources.validation.secretForTest") });
    return;
  }
  setTesting(true);
  try {
    const result = editingId
      ? await testSource(editingId, { engine: values.engine, access: values.access })
      : await testSourceDraft({ engine: values.engine, access: values.access });
    if (result.ok) {
      open?.({ type: "success", message: t("sources.test.success") });
    } else {
      open?.({ type: "error", message: result.message || t("sources.test.failed") });
    }
  } catch (err) {
    open?.({ type: "error", message: problemMessage(t, err, String(err)) });
  } finally {
    setTesting(false);
  }
}
