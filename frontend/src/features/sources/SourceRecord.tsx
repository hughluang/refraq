"use client";

import { Box, Button, Divider, Group, Modal, Paper, SimpleGrid, Stack, Text, Title, Tooltip } from "@mantine/core";
import { useCan, useNotification, usePermissions, useTranslate } from "@refinedev/core";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { FormSection } from "@/components/form/FormSection";
import { SourceConnectionProbe } from "@/features/sources/SourceConnectionProbe";
import { DisplayField } from "@/components/display/DisplayField";
import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { presentSaveFailure } from "@/components/feedback/presentSaveFailure";
import { SelectField } from "@/components/form/SelectField";
import { SwitchField } from "@/components/form/SwitchField";
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
import { SpecTree, defaultsFromSchema, validateSourceAccess } from "@/features/sources/SpecTree";
import { StructureDiffList } from "@/features/sources/structure-diffs/StructureDiffList";
import type {
  ConnectorSpec,
  Engine,
  Source,
  SourceAccess,
} from "@/features/sources/types";
import { useConfirmAction } from "@/hooks/useConfirmAction";
import { ApiError } from "@/lib/api";

import "./source-record.css";

const FORM_ID = "source-record-form";
const DEFAULT_ENGINE: Engine = "postgresql";

type Values = {
  key: string;
  name: string;
  description: string;
  status: "active" | "disabled";
  engine: Engine | "";
  access: SourceAccess;
  captureIntent: "retain" | "replace" | "clear";
  captureUsername: string;
  capturePassword: string;
  anyTime: boolean;
  windowStart: string;
  windowEnd: string;
};

type Props = { mode: "create" } | { mode: "show" | "edit"; sourceId: string };

const EMPTY: Values = {
  key: "",
  name: "",
  description: "",
  status: "active",
  engine: "",
  access: {},
  captureIntent: "retain",
  captureUsername: "",
  capturePassword: "",
  anyTime: true,
  windowStart: "",
  windowEnd: "",
};

function formEngine(engine: string | null | undefined): Engine {
  return selectedEngine(engine ?? "") ?? DEFAULT_ENGINE;
}

function valuesFrom(source: Source, access: SourceAccess): Values {
  return {
    ...EMPTY,
    key: source.key,
    name: source.name,
    description: source.description ?? "",
    status: source.status === "disabled" ? "disabled" : "active",
    engine: formEngine(source.engine),
    access,
    anyTime: source.snapshot_window == null,
    windowStart: source.snapshot_window?.start ?? "",
    windowEnd: source.snapshot_window?.end ?? "",
  };
}

function snapshotWrite(values: Values, existing?: Source) {
  const window = values.anyTime ? null : { start: values.windowStart, end: values.windowEnd };
  const previous = existing?.snapshot_window;
  if (existing && window?.start === previous?.start && window?.end === previous?.end) return {};
  return { snapshot_window: window };
}

function captureWrite(values: Values) {
  if (values.captureIntent === "clear") return { capture_credential: null };
  if (values.captureIntent === "replace") {
    return { capture_credential: { username: values.captureUsername, password: values.capturePassword } };
  }
  return {};
}

const CAPTURE_ERROR_ALIASES = {
  "capture_credential.username": "captureUsername",
  "capture_credential.password": "capturePassword",
  capture_credential: "captureUsername",
  "snapshot_window.start": "windowStart",
  "snapshot_window.end": "windowEnd",
  snapshot_window: "windowStart",
};

function validateDefinition(values: Values, schema: ConnectorSpec | null, create: boolean, t: (key: string) => string) {
  const errors: Record<string, string> = {};
  const required = t("sources.validation.required");
  if (create && !values.key.trim()) errors.key = required;
  if (!values.name.trim()) errors.name = required;
  if (!values.engine) errors.engine = required;
  if (schema) Object.assign(errors, validateSourceAccess(schema, values.access, t));
  if (values.captureIntent === "replace") {
    if (!values.captureUsername) errors.captureUsername = required;
    if (!values.capturePassword) errors.capturePassword = required;
  }
  if (!values.anyTime) {
    const time = /^(?:[01][0-9]|2[0-3]):[0-5][0-9]$/;
    if (!time.test(values.windowStart)) errors.windowStart = t("sources.capture.invalidTime");
    if (!time.test(values.windowEnd)) errors.windowEnd = t("sources.capture.invalidTime");
    else if (values.windowEnd === values.windowStart) errors.windowEnd = t("sources.capture.equalTime");
  }
  return errors;
}

function focusSourceError(getInputNode: (path: string) => HTMLElement | null, path: string | undefined) {
  if (!path) return;
  requestAnimationFrame(() => {
    const input = document.getElementsByName(path)[0] ?? getInputNode(path);
    const panel = input?.closest("details");
    if (panel) panel.open = true;
    input?.focus();
  });
}

function useEngineSwitch(form: UseConsoleFormReturn<Values>, setSchema: (schema: ConnectorSpec) => void, existing: boolean) {
  const t = useTranslate();
  const confirm = useConfirmAction<Engine>();
  const [switching, setSwitching] = useState(false);
  const pending = useRef(false);

  async function apply(next: Engine) {
    if (pending.current) return;
    pending.current = true;
    setSwitching(true);
    try {
      const { schema } = await getAccessSchema(next);
      form.setValues({ engine: next, access: defaultsFromSchema(schema) });
      for (const path of Object.keys(form.errors)) {
        if (path.startsWith("access.")) form.clearFieldError(path);
      }
      setSchema(schema);
    } catch (err) {
      presentProblemNotification(t, err);
    } finally {
      pending.current = false;
      setSwitching(false);
    }
  }

  function choose(next: Engine | null) {
    if (!next || next === form.values.engine || pending.current) return;
    if (existing || form.isDirty("access")) confirm.open(next);
    else void apply(next);
  }

  return { switching, choose, dialog: <EngineSwitchDialog confirm={confirm} onApply={(next) => void apply(next)} /> };
}

export function SourceRecord(props: Props) {
  if (props.mode === "create") return <SourceCreate />;
  return <SourceExisting key={props.mode + props.sourceId} mode={props.mode} sourceId={props.sourceId} />;
}

function SourceCreate() {
  const t = useTranslate();
  const { open } = useNotification();
  const [schema, setSchema] = useState<ConnectorSpec | null>(null);
  const [ready, setReady] = useState(false);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);
  const form = useConsoleForm<Values>({
    initialValues: EMPTY,
    validate: (values) => validateDefinition(values, schema, true, t),
  });

  const engineSwitch = useEngineSwitch(form, setSchema, false);

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
                <Button type="submit" form={FORM_ID} size="sm" loading={form.submitting} disabled={engineSwitch.switching}>
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
            ...captureWrite(values),
            ...snapshotWrite(values),
          })
            .then((created) => {
              form.setValues({ ...values, captureIntent: "retain", captureUsername: "", capturePassword: "" });
              form.markSaved();
              suppressLeaveGuard();
              open?.({ type: "success", message: t("sources.create.success") });
              window.location.replace(sourceEditPath(created.source.id));
            })
            .catch((err: unknown) => {
              presentSaveFailure(t, err, (error) => form.applyApiError(error, CAPTURE_ERROR_ALIASES));
            });
        }, (errors) => focusSourceError(form.getInputNode, Object.keys(errors)[0]))}
      >
        <SourceFields
          form={form}
          schema={schema}
          mode="create"
          editable
          canTest
          switching={engineSwitch.switching}
          onEngineChange={engineSwitch.choose}
        />
      </form>
      {engineSwitch.dialog}
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
  const [editingAccess, setEditingAccess] = useState(false);
  const [loadingAccess, setLoadingAccess] = useState(false);
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
  const form = useConsoleForm<Values>({
    initialValues: EMPTY,
    validate: (values) => validateDefinition(values, editingAccess ? schema : null, false, t),
  });

  const engineSwitch = useEngineSwitch(form, setSchema, true);
  const formRef = useRef(form);
  formRef.current = form;
  const tRef = useRef(t);
  tRef.current = t;

  const loadGeneration = useRef(0);
  const load = useCallback(
    async () => {
      if (mode === "edit" && !writeReady) return;
      if (permissionsLoading || permissions == null) return;
      const generation = ++loadGeneration.current;
      const translate = tRef.current;
      const currentForm = formRef.current;
      setLoading(true);
      setLoadFailed(false);
      setMissing(false);
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
        if (generation !== loadGeneration.current) return;
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
        const [schemaRes, allowMembers] = await Promise.all([
          getAccessSchema(engine),
          canListMembers(sourceId, canManageAccess),
        ]);
        if (generation !== loadGeneration.current) return;
        setSchema(schemaRes.schema);
        currentForm.setValues(valuesFrom(loaded, loaded.access ?? {}));
        currentForm.markSaved();
        setRecord(loaded);
        setEditingAccess(false);
        setIdentityOnly(false);
        setMissing(false);
        setLoadFailed(false);
        setMembersAllowed(allowMembers);
      } catch (err) {
        if (generation !== loadGeneration.current) return;
        setLoadFailed(true);
        presentProblemNotification(translate, err, { onRetry: () => void load() });
      } finally {
        if (generation === loadGeneration.current) setLoading(false);
      }
    },
    [canManageAccess, canReadSources, mode, permissions, permissionsLoading, sourceId, writeReady],
  );

  useEffect(() => {
    void load();
    return () => { loadGeneration.current += 1; };
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
    if (mode === "edit" && (canWrite?.can === false || (record && !record.can_write))) {
      replace(sourceShowPath(sourceId, tab));
    }
  }, [canWrite?.can, mode, record, replace, sourceId, tab]);

  if (mode === "edit" && canWrite?.can !== true) {
    return <PageChrome title={t("sources.title")} status="loading" />;
  }

  if (loading || loadFailed || !record) {
    return (
      <PageChrome
        title={t("sources.title")}
        status={missing ? "notFound" : loadFailed ? "unloaded" : "loading"}
        onRetry={loadFailed ? () => void load() : undefined}
      />
    );
  }

  const writable = Boolean(record.can_write && canWrite?.can);
  const editable = mode === "edit" && writable;
  const editAccess = async () => {
    setLoadingAccess(true);
    try {
      const { access } = await getSourceAccess(sourceId);
      form.setInitialValues(valuesFrom(record, access));
      form.setFieldValue("access", access);
      setEditingAccess(true);
    } catch (error) {
      presentProblemNotification(t, error);
    } finally {
      setLoadingAccess(false);
    }
  };
  function focusDefinitionError(errors: Record<string, ReactNode>) {
    consoleTab.setTab(SOURCE_RECORD_TAB);
    focusSourceError(form.getInputNode, Object.keys(errors)[0]);
  }

  const save = async (values: Values) => {
    const engine = selectedEngine(values.engine);
    if (!engine) return;
    try {
      const name = values.name.trim();
      const description = values.description.trim() || null;
      const engineChanged = engine !== record.engine;
      const updated = await patchSource(sourceId, {
        ...(form.isDirty("name") && name !== record.name && { name }),
        ...(form.isDirty("description") && description !== (record.description || null) && { description }),
        ...(values.status !== record.status && { status: values.status }),
        ...(engineChanged && { engine }),
        ...(editingAccess && (form.isDirty("access") || engineChanged) && { access: values.access }),
        ...captureWrite(values),
        ...snapshotWrite(values, record),
      });
      setRecord(updated.source);
      setEditingAccess(false);
      form.setValues(valuesFrom(updated.source, updated.source.access ?? {}));
      form.markSaved();
      open?.({ type: "success", message: t("sources.update.success") });
      if (updated.schedules && updated.schedules.length > 0) {
        open?.({ type: "success", message: t("schedules.seededOnSourceUpdate") });
      }
    } catch (err) {
      presentSaveFailure(t, err, (error) => {
        const result = form.applyApiError(error, CAPTURE_ERROR_ALIASES);
        if (result.mapped.length) {
          consoleTab.setTab(SOURCE_RECORD_TAB);
          requestAnimationFrame(() => document.querySelector<HTMLElement>("#source-record-form [aria-invalid=true]")?.focus());
        }
        return result;
      });
    }
  };

  const fields = (
    <SourceFields
      form={form}
      schema={schema}
      mode={mode}
      editable={editable}
      identityOnly={identityOnly}
      source={record}
      connectionEditable={editable && editingAccess}
      onEditConnection={editable && !editingAccess ? editAccess : undefined}
      loadingAccess={loadingAccess}
      canTest={writable}
      switching={engineSwitch.switching}
      onEngineChange={engineSwitch.choose}
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
                    disabled={form.dirty || form.submitting || loadingAccess || engineSwitch.switching}
                    onClick={() => {
                      setReloadKey((value) => value + 1);
                      void load();
                    }}
                  >
                    {t("jobs.refresh")}
                  </Button>
                </>
              }
              standard={recordStandard({
                mode: editable ? "edit" : "show",
                canWrite: writable,
                canDelete: Boolean(canDelete?.can && record.can_write),
                deletable: record.status === "disabled",
                submitting: form.submitting,
                saveDisabled: loadingAccess || engineSwitch.switching,
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
              <form id={FORM_ID} noValidate onSubmit={form.onSubmit(save, focusDefinitionError)}>
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
          {engineSwitch.dialog}
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
  saveDisabled,
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
  saveDisabled: boolean;
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
          <Button type="submit" form={FORM_ID} size="sm" loading={submitting} disabled={saveDisabled}>
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
  source,
  canTest,
  switching,
  connectionEditable = editable,
  onEditConnection,
  loadingAccess,
  onEngineChange,
}: {
  form: UseConsoleFormReturn<Values>;
  schema: ConnectorSpec | null;
  mode: "create" | "show" | "edit";
  editable: boolean;
  identityOnly?: boolean;
  source?: Source;
  canTest: boolean;
  switching: boolean;
  connectionEditable?: boolean;
  onEditConnection?: () => void;
  loadingAccess?: boolean;
  onEngineChange: (next: Engine | null) => void;
}) {
  const t = useTranslate();
  const engine = selectedEngine(form.values.engine);
  const engineOptions = SOURCE_ENGINES.map((value) => ({ value, label: engineLabel(t, value) }));
  const engineField = (
    <SelectField
      label={t("sources.fields.engine")}
      data={engineOptions}
      required={connectionEditable}
      editable={connectionEditable}
      {...form.fieldProps("engine")}
      value={engine}
      onChange={(value) => onEngineChange(selectedEngine(value ?? "") ?? null)}
    />
  );
  function validateProbe() {
    if (!schema) return false;
    const errors = validateSourceAccess(schema, form.values.access, t);
    for (const path of Object.keys(form.errors)) {
      if (path.startsWith("access.")) form.clearFieldError(path);
    }
    for (const [path, message] of Object.entries(errors)) form.setFieldError(path, message);
    const [first] = Object.keys(errors);
    focusSourceError(form.getInputNode, first);
    return !first;
  }

  return (
    <fieldset disabled={form.submitting} className="source-record-fields">
      <Stack gap="lg">
        <Paper withBorder p="md">
          <FormSection title={t("sources.workflow.identity")}>
            <TextField label={t("sources.fields.key")} required={mode === "create"} editable={mode === "create"} {...form.fieldProps("key")} />
            <TextField label={t("sources.fields.name")} required={editable} editable={editable} {...form.fieldProps("name")} />
            {!identityOnly && (
              <TextareaField
                label={t("sources.fields.description")}
                autosize minRows={2}
                style={{ gridColumn: "1 / -1" }}
                editable={editable} {...form.fieldProps("description")}
              />
            )}
            {mode !== "create" && (
              <SelectField
                label={t("sources.fields.status")}
                data={["active", "disabled"].map((value) => ({ value, label: t(`sources.status.${value}`) }))}
                editable={editable} {...form.fieldProps("status")}
              />
            )}
            {identityOnly && engineField}
          </FormSection>
        </Paper>
        {!identityOnly && (
          <>
            <Paper withBorder p="md">
              <Stack gap="md">
                <fieldset disabled={switching} aria-busy={switching} className="source-record-fields">
                  <Stack gap="md">
                    <FormSection title={t("sources.workflow.connection")}>
                      {engineField}
                      {onEditConnection && (
                        <Group align="end">
                          <Button type="button" size="sm" variant="default" loading={loadingAccess} onClick={onEditConnection}>
                            {t("sources.workflow.editConnection")}
                          </Button>
                        </Group>
                      )}
                    </FormSection>
                    <SpecTree
                      key={engine}
                      schema={schema}
                      value={form.values.access}
                      onChange={(next) => {
                        form.setFieldValue("access", next);
                        if (schema && Object.keys(form.errors).some((key) => key.startsWith("access."))) {
                          const errors = validateSourceAccess(schema, next, t);
                          for (const path of Object.keys(form.errors)) {
                            if (path.startsWith("access.")) form.setFieldError(path, errors[path]);
                          }
                        }
                      }}
                      editable={connectionEditable}
                      errors={form.errors}
                    />
                  </Stack>
                </fieldset>
                {canTest && engine && (
                  <>
                    <Divider />
                    <SourceConnectionProbe
                      key={source?.access_updated_at}
                      sourceId={source?.id}
                      engine={engine}
                      draft={!source || (connectionEditable && (form.isDirty("access") || form.isDirty("engine"))) ? form.values.access : undefined}
                      disabled={switching || form.submitting || Boolean(loadingAccess)}
                      validateDraft={validateProbe}
                    />
                  </>
                )}
              </Stack>
            </Paper>
            <CaptureSettings form={form} source={source} editable={editable} />
          </>
        )}
      </Stack>
    </fieldset>
  );
}

function CaptureSettings({ form, source, editable }: {
  form: UseConsoleFormReturn<Values>;
  source?: Source;
  editable: boolean;
}) {
  const t = useTranslate();
  const catalog = useCan({ resource: ModuleId.catalog, action: ModuleAction.list });
  const [expanded, setExpanded] = useState(Boolean(source?.capture_credential_set || source?.snapshot_window));
  const intent = form.values.captureIntent;
  useEffect(() => {
    if (form.errors.captureUsername || form.errors.capturePassword || form.errors.windowStart || form.errors.windowEnd) {
      setExpanded(true);
    }
  }, [form.errors]);
  const configured = Boolean(source?.capture_credential_set);
  const credential = t(configured ? "sources.capture.set" : "sources.capture.unset");
  const credentialSummary = intent === "retain" ? credential : t(
    intent === "clear" ? "sources.workflow.credentialCleared" : "sources.workflow.credentialPending",
  );
  const windowSummary = form.values.anyTime
    ? t("sources.capture.anyTime")
    : [form.values.windowStart, form.values.windowEnd].filter(Boolean).join("–") || t("sources.workflow.window");
  const changeIntent = (captureIntent: Values["captureIntent"]) => {
    form.setValues({ captureIntent, captureUsername: "", capturePassword: "" });
    form.clearFieldError("captureUsername");
    form.clearFieldError("capturePassword");
  };
  return (
    <Paper withBorder p="md">
      <Stack gap="md">
        <Group justify="space-between" align="center">
          <Stack gap={2}>
            <Title order={2}>{t("sources.workflow.capture")}</Title>
            {!expanded && <Text size="sm" c="dimmed">{credentialSummary} · {windowSummary}</Text>}
          </Stack>
          <Button
            type="button" size="sm" variant="subtle" aria-expanded={expanded}
            aria-controls="source-capture-settings" onClick={() => setExpanded(!expanded)}
          >
            {t(expanded ? "sources.workflow.hideCapture" : "sources.workflow.showCapture")}
          </Button>
        </Group>
        {source?.kind === "database" && catalog.data?.can && (
          <Button component={ConsoleLink} href={`/console/catalog?source=${encodeURIComponent(source.id)}`} variant="light" size="sm" w="fit-content">
            {t("catalog.chooseSyncTable")}
          </Button>
        )}
        <Stack id="source-capture-settings" gap="lg" hidden={!expanded} style={!expanded ? { display: "none" } : undefined}>
          <Stack gap="sm">
            <DisplayField label={t("sources.capture.credential")} value={credential} helper={t("sources.capture.helper")} />
            {editable && (
              <Group gap="xs">
                {intent === "retain" ? (
                  <>
                    <Button type="button" variant="default" size="sm" onClick={() => changeIntent("replace")}>
                      {t(configured ? "sources.capture.replace" : "sources.workflow.setCredential")}
                    </Button>
                    {configured && (
                      <Button type="button" variant="light" color="red" size="sm" onClick={() => changeIntent("clear")}>
                        {t("sources.capture.clear")}
                      </Button>
                    )}
                  </>
                ) : (
                  <Button type="button" variant="default" size="sm" onClick={() => changeIntent("retain")}>
                    {t("sources.workflow.undoCredential")}
                  </Button>
                )}
              </Group>
            )}
            {intent === "clear" && <Text size="sm" c="red">{t("sources.capture.clearHint")}</Text>}
            {intent === "replace" && (
              <SimpleGrid cols={{ base: 1, sm: 2 }}>
                <TextField editable label={t("sources.capture.username")} required autoComplete="off" {...form.fieldProps("captureUsername")} />
                <TextField editable type="password" label={t("sources.capture.password")} required autoComplete="new-password" {...form.fieldProps("capturePassword")} />
              </SimpleGrid>
            )}
          </Stack>
          <FormSection order={3} title={t("sources.workflow.window")}>
            <DisplayField label={t("sources.capture.timezone")} value={source?.schedule_timezone} helper={!source?.schedule_timezone ? t("sources.capture.timezonePending") : undefined} />
            <SwitchField editable={editable} label={t("sources.capture.anyTime")} helper={t("sources.capture.windowHelper")} {...form.fieldProps("anyTime", { type: "checkbox" })} />
            {!form.values.anyTime && (
              <>
                <TextField editable={editable} label={t("sources.capture.start")} placeholder="HH:mm" required={editable} {...form.fieldProps("windowStart")} />
                <TextField editable={editable} label={t("sources.capture.end")} placeholder="HH:mm" required={editable} {...form.fieldProps("windowEnd")} />
              </>
            )}
          </FormSection>
        </Stack>
      </Stack>
    </Paper>
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
