"use client";

import { Button, Group, Stack } from "@mantine/core";
import {
  CanAccess,
  useCan,
  useNotification,
  usePermissions,
  useTranslate,
} from "@refinedev/core";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { DisplayField } from "@/components/display/DisplayField";
import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import { useConsoleMutation } from "@/components/feedback/useConsoleMutation";
import { EmptyState } from "@/components/feedback/EmptyState";
import { HeaderAction, HeaderActions } from "@/components/layout/HeaderActions";
import { PageChrome } from "@/components/layout/PageChrome";
import { useConsoleTab } from "@/components/layout/consoleTabs";
import {
  FormErrorSummary,
  saveFailureFrom,
  type SaveFailure,
} from "@/components/form/FormErrorSummary";
import { useConsoleForm } from "@/components/form/useConsoleForm";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { suppressLeaveGuard } from "@/components/navigation/leaveGuard";
import { useConsoleNavigation } from "@/components/navigation/useConsoleNavigation";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import {
  type AttributeReveal,
} from "@/features/entities/AttributeEditor";
import {
  attributeDraftIssues,
  attributeIndexFromPath,
  firstAttributeErrorIndex,
  type AttributeIssueField,
} from "@/features/entities/attributeDraftValidation";
import { EntityAttributesTab } from "@/features/entities/EntityAttributesTab";
import { EntityAccessTab } from "@/features/entities/EntityAccessTab";
import { EntityChangeLogTab } from "@/features/entities/EntityChangeLogTab";
import { EntityDataBrowser } from "@/features/entities/EntityDataBrowser";
import { EntityChangeLogFields } from "@/features/entities/EntityChangeLogFields";
import { EntityIdentityFields } from "@/features/entities/EntityIdentityFields";
import { EntityOverviewTab } from "@/features/entities/EntityOverviewTab";
import { EntityTabs } from "@/features/entities/EntityTabs";
import { EntityVersionsTab } from "@/features/entities/EntityVersionsTab";
import { EntityStatusBadge } from "@/features/entities/EntityStatusBadge";
import {
  EntityTagsControl,
  type EntityTagsControlHandle,
} from "@/features/entities/EntityTagsControl";
import {
  createEntity,
  deleteEntity,
  deprecateEntity,
  enqueueDropTable,
  getEntity,
  getVersion,
  listVersions,
  openVersion,
  patchEntity,
  publishVersion,
} from "@/features/entities/api";
import { EntityPublishConfirm } from "@/features/entities/EntityPublishConfirm";
import { ACCESS_MANAGE_PERMISSION, DATA_READ_PERMISSION, DROP_TABLE_PERMISSION } from "@/features/entities/constants";
import {
  createFormErrorTab,
  entityDetailHref,
  entityEditHref,
  parseEntityDetailTab,
} from "@/features/entities/entityDetailTab";
import {
  attributesFromDrafts,
  draftsFromVersion,
} from "@/features/entities/entityPresentation";
import {
  ENTITY_RECORD_FORM_ID,
  entityRecordHeaderActions,
  type EntityRecordMode,
} from "@/features/entities/entityRecordActions";
import { canAuthor, isPublishing } from "@/features/entities/publishStatus";
import type {
  BusinessEntity,
  EffectiveChangeLog,
  EntityRecordFormValues,
  EntityTag,
  EntityVersion,
} from "@/features/entities/types";
import { getJob } from "@/features/jobs/api";
import { JobDetailModal } from "@/features/jobs/JobDetailModal";
import { useConfirmAction } from "@/hooks/useConfirmAction";
import { useFormatInstant } from "@/hooks/useFormatInstant";
import { useLiveStatus } from "@/hooks/useLiveStatus";
import { problemMessage } from "@/lib/problem";

export type { EntityRecordMode };

type Props =
  | { mode: "create" }
  | { mode: "show" | "edit"; entityId: string };

const EMPTY_TAGS: EntityTag[] = [];

/** Canonical decimal text of an integer of at least 1. No leading zero, no fraction. */
const WHOLE_RETENTION_DAYS = /^[1-9]\d*$/;

function retentionDraft(days: number | null | undefined): string {
  return days == null ? "" : String(days);
}

/** Empty is never-expire. Call only after the draft has passed validation. */
function retentionDays(value: string): number | null {
  if (value === "") return null;
  return Number(value);
}

function inflightReconcileJobId(version: EntityVersion | null): string | null {
  const id = version?.alignment.latest_job_id;
  const status = version?.alignment.latest_job_status;
  if (id && (status === "queued" || status === "running")) return id;
  return null;
}

function jobIsTerminal(status: string): boolean {
  return status === "succeeded" || status === "failed" || status === "cancelled";
}

export function EntityRecord(props: Props) {
  const mode = props.mode;
  const entityId = props.mode === "create" ? undefined : props.entityId;
  const t = useTranslate();
  const { open } = useNotification();
  const openVersionAction = useConsoleMutation();
  const { push, replace } = useConsoleNavigation();
  const formatInstant = useFormatInstant();
  const { data: canWrite } = useCan({
    resource: ModuleId.entities,
    action: ModuleAction.edit,
  });
  const { data: permissions } = usePermissions<string[]>({});
  const canDropTable =
    Array.isArray(permissions) && permissions.includes(DROP_TABLE_PERMISSION);
  const canAccess =
    Array.isArray(permissions) && permissions.includes(ACCESS_MANAGE_PERMISSION);
  const canData =
    Array.isArray(permissions) && permissions.includes(DATA_READ_PERMISSION);

  const [entity, setEntity] = useState<BusinessEntity | null>(null);
  const recordingOn = entity?.change_log_recording === true;

  const tabItems = useMemo(() => {
    const items = [
      { value: "overview" },
      { value: "attributes" },
      { value: "versions" },
    ];
    if (mode !== "create" && canAccess) items.push({ value: "access" });
    if (mode !== "create" && canData) items.push({ value: "data" });
    if (mode !== "create" && canData && recordingOn) {
      items.push({ value: "change_log" });
    }
    return items;
  }, [canAccess, canData, mode, recordingOn]);
  const consoleTab = useConsoleTab(tabItems);
  const tab = parseEntityDetailTab(consoleTab.value);
  const setTab = consoleTab.setTab;

  const [versions, setVersions] = useState<EntityVersion[]>([]);
  const [current, setCurrent] = useState<EntityVersion | null>(null);
  const [loading, setLoading] = useState(mode !== "create");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobOpened, setJobOpened] = useState(false);
  const [watchedJobId, setWatchedJobId] = useState<string | null>(null);
  const reloadedJobId = useRef<string | null>(null);

  const dropConfirm = useConfirmAction<EntityVersion>();
  const publishConfirm = useConfirmAction<true>();
  const lifecycle = useConsoleMutation();

  const [attributeEditorOpen, setAttributeEditorOpen] = useState(false);
  const [attributeReveal, setAttributeReveal] = useState<AttributeReveal | null>(
    null,
  );
  const [tagDraft, setTagDraft] = useState<{ tag_ids: string[]; names: string[] }>({
    tag_ids: [],
    names: [],
  });
  const tagsControl = useRef<EntityTagsControlHandle>(null);

  const attributeFieldMessage = (
    values: EntityRecordFormValues,
    path: string,
    field: AttributeIssueField,
  ): string | null => {
    const index = attributeIndexFromPath(path);
    if (index == null) return null;
    const draft = values.attributes[index];
    if (!draft) return null;
    const issue = attributeDraftIssues(
      draft,
      values.attributes.map((item) => item.name),
      values.attributes.filter((_, itemIndex) => itemIndex !== index),
    ).find((item) => item.field === field);
    if (!issue) return null;
    return issue.values ? t(issue.key, issue.values) : t(issue.key);
  };

  const [saveFailure, setSaveFailure] = useState<SaveFailure | null>(null);
  const form = useConsoleForm<EntityRecordFormValues>({
    onValuesChange: () => setSaveFailure(null),
    initialValues: {
      table_name: "",
      name: "",
      description: "",
      attributes: [],
      change_log_enabled: false,
      change_log_retention_days: "",
    },
    validate: {
      table_name: (value) =>
        mode === "create" && !value.trim()
          ? t("entities.validation.required")
          : null,
      name: (value) =>
        value.trim() ? null : t("entities.validation.required"),
      description: (value) =>
        value.trim() ? null : t("entities.validation.required"),
      change_log_retention_days: (value) => {
        if (value === "" || WHOLE_RETENTION_DAYS.test(value)) return null;
        return t("entities.validation.changeLogRetention");
      },
      attributes: {
        name: (_value, values, path) =>
          attributeFieldMessage(values, path, "name"),
        max_length: (_value, values, path) =>
          attributeFieldMessage(values, path, "max_length"),
        precision: (_value, values, path) =>
          attributeFieldMessage(values, path, "precision"),
        scale: (_value, values, path) =>
          attributeFieldMessage(values, path, "scale"),
        dictionary_id: (_value, values, path) =>
          attributeFieldMessage(values, path, "dictionary_id"),
        target_entity_id: (_value, values, path) =>
          attributeFieldMessage(values, path, "target_entity_id"),
      },
    },
  });

  const loadGeneration = useRef(0);

  const load = useCallback(async () => {
    if (!entityId) return;
    const generation = ++loadGeneration.current;
    setLoading(true);
    setError(null);
    try {
      const [entityRes, versionsRes] = await Promise.all([
        getEntity(entityId),
        listVersions(entityId, { limit: 200 }),
      ]);
      if (generation !== loadGeneration.current) return;
      const loaded = entityRes.entity;
      const currentId = loaded.current_version?.id;
      let version: EntityVersion | null = null;
      if (currentId) {
        const versionRes = await getVersion(entityId, currentId);
        if (generation !== loadGeneration.current) return;
        version = versionRes.version;
      }
      setEntity(loaded);
      setVersions(versionsRes.items);
      setCurrent(version);
      form.setValues({
        table_name: loaded.table_name,
        name: loaded.name,
        description: loaded.description,
        attributes: version ? draftsFromVersion(version) : [],
        change_log_enabled: version?.change_log_enabled ?? false,
        change_log_retention_days: retentionDraft(version?.change_log_retention_days),
      });
      form.markSaved();
    } catch (err) {
      if (generation !== loadGeneration.current) return;
      setError(problemMessage(t, err, String(err)));
      setEntity(null);
    } finally {
      if (generation === loadGeneration.current) setLoading(false);
    }
  }, [entityId]);

  const publishJobId = inflightReconcileJobId(current);
  const followedJobId = publishJobId ?? watchedJobId;

  const watchedJob = useLiveStatus({
    enabled: followedJobId != null,
    key: followedJobId,
    fetch: async (signal) => {
      const body = await getJob(followedJobId as string, { signal });
      return body.job;
    },
    isTerminal: (job) => jobIsTerminal(job.status),
  });

  useEffect(() => {
    const job = watchedJob.data;
    if (!job || !jobIsTerminal(job.status) || reloadedJobId.current === job.id) {
      return;
    }
    reloadedJobId.current = job.id;
    void load();
  }, [load, watchedJob.data]);

  useEffect(() => {
    if (mode === "create") return;
    void load();
  }, [load, mode]);

  useEffect(() => {
    if (mode !== "edit" || !entityId || !entity) return;
    if (canAuthor(entity)) return;
    suppressLeaveGuard();
    replace(entityDetailHref(entityId, tab));
  }, [entity, entityId, mode, replace, tab]);

  useEffect(() => {
    if (!Array.isArray(permissions) || mode === "create") return;
    const hidden =
      (tab === "access" && !canAccess) || (tab === "data" && !canData);
    if (!hidden) return;
    setTab("overview");
  }, [canAccess, canData, entityId, mode, permissions, setTab, tab]);

  const selectTab = (next: typeof tab) => {
    setTab(next);
  };

  const notifyError = (err: unknown, fallback: string) => {
    open?.({
      type: "error",
      message: problemMessage(t, err, fallback),
    });
  };

  const openJob = (id: string | null) => {
    if (!id) return;
    setJobId(id);
    setJobOpened(true);
  };

  const fieldsWritable =
    mode === "create" ||
    (mode === "edit" &&
      Boolean(canWrite?.can) &&
      entity != null &&
      canAuthor(entity));

  const submit = async (values: EntityRecordFormValues) => {
    if (canWrite?.can === false) return;
    try {
      if (mode === "create") {
        const created = await createEntity({
          table_name: values.table_name.trim(),
          name: values.name.trim(),
          description: values.description.trim(),
          attributes: attributesFromDrafts(values.attributes),
          tags: tagsControl.current?.flush() ?? tagDraft,
          change_log_enabled: values.change_log_enabled,
          change_log_retention_days: retentionDays(values.change_log_retention_days),
        });
        form.markSaved();
        suppressLeaveGuard();
        open?.({ type: "success", message: t("entities.create.success") });
        window.location.replace(entityEditHref(created.entity.id, "attributes"));
        return;
      }
      if (mode !== "edit" || !entityId) return;
      await patchEntity(entityId, {
        name: values.name.trim(),
        description: values.description.trim(),
        attributes: attributesFromDrafts(values.attributes),
        change_log_enabled: values.change_log_enabled,
        change_log_retention_days: retentionDays(values.change_log_retention_days),
      });
      form.markSaved();
      setSaveFailure(null);
      open?.({ type: "success", message: t("entities.update.success") });
      await load();
    } catch (err) {
      setSaveFailure(
        saveFailureFrom(
          t,
          err,
          form.applyApiError(err),
          mode === "create" ? String(err) : t("entities.update.failed"),
        ),
      );
    }
  };

  const confirmPublish = async () => {
    if (!entityId || !current) return;
    setBusy(true);
    try {
      const result = await publishVersion(entityId, current.id);
      publishConfirm.close();
      if (result.job) {
        open?.({ type: "success", message: t("entities.publish.queued") });
        openJob(result.job.id);
      }
      await load();
    } catch (err) {
      notifyError(err, t("entities.publish.failed"));
    } finally {
      setBusy(false);
    }
  };

  function onDeprecate() {
    if (!entityId || !entity) return;
    lifecycle.run({
      safety: "confirm",
      key: "deprecate",
      recordName: entity.name,
      title: t("entities.deprecate.confirmTitle"),
      consequence: t("entities.deprecate.consequence"),
      confirmLabel: t("entities.deprecate"),
      confirmColor: "red",
      outcome: t("entities.deprecate.success"),
      execute: () => deprecateEntity(entityId),
      onSuccess: () => load(),
    });
  }

  function onDeleteEntity() {
    if (!entityId || !entity) return;
    lifecycle.run({
      safety: "confirm",
      key: "delete",
      recordName: entity.name,
      title: t("entities.delete.confirmTitle"),
      consequence: t("entities.delete.consequence"),
      confirmLabel: t("actions.delete"),
      confirmColor: "red",
      outcome: t("entities.delete.success"),
      execute: async () => {
        await deleteEntity(entityId);
        suppressLeaveGuard();
        push("/console/entities");
      },
    });
  }

  const confirmDrop = async () => {
    const pending = dropConfirm.pending;
    if (!pending || !entityId) return;
    setBusy(true);
    try {
      const result = await enqueueDropTable(entityId, pending.id);
      dropConfirm.close();
      if (result.job) {
        open?.({ type: "success", message: t("entities.drop.queued") });
        openJob(result.job.id);
        setWatchedJobId(result.job.id);
      } else {
        open?.({ type: "success", message: t("entities.drop.noop") });
      }
      await load();
    } catch (err) {
      notifyError(err, t("entities.drop.failed"));
    } finally {
      setBusy(false);
    }
  };

  if (mode !== "create" && loading && !entity) {
    return (
      <PageChrome
        title={t("entities.title")}
        description={t("entities.description")}
        status="loading"
      />
    );
  }

  if (mode !== "create" && (error || !entity)) {
    return (
      <PageChrome
        title={t("entities.title")}
        description={t("entities.description")}
        status={error ? "error" : "notFound"}
        errorMessage={error ?? undefined}
        onRetry={error ? () => void load() : undefined}
      />
    );
  }

  if (mode === "edit" && entity && !canAuthor(entity)) {
    return <PageChrome title={t("entities.edit.title")} status="loading" />;
  }

  const writable = entity ? canAuthor(entity) : false;
  const publishing = entity ? isPublishing(entity) : false;
  const deprecated = Boolean(entity?.deprecated_at);
  const dirty = form.isDirty();
  const savedEmpty = (current?.attributes ?? []).length === 0;
  const published = entity?.current_version?.publish_status === "published";
  const recordTitle =
    mode === "create" || !entity ? undefined : `${entity.name} · ${entity.table_name}`;
  const title = recordTitle ? t("entities.title") : mode === "create"
    ? t("entities.create.title")
    : t("entities.edit.title");

  const header = entityRecordHeaderActions({
    mode,
    canWrite: Boolean(canWrite?.can),
    canAuthor: writable,
    publishing,
    deprecated,
    published,
    everPublished: Boolean(entity?.ever_published),
    hasCurrentVersion: current != null,
  });

  const navigationActions = header.navigation ? (
      <Group gap="xs" wrap="nowrap" aria-label={t("entities.actions.navigation")}>
        <Button
          component={ConsoleLink}
          href="/console/entities"
          variant="default"
          size="sm"
        >
          {t("entities.backToList")}
        </Button>
        <Button size="sm" variant="light" onClick={() => void load()}>
          {t("jobs.refresh")}
        </Button>
      </Group>
  ) : null;
  const lifecycleActions = header.lifecycle ? (
      <Group gap="xs" wrap="nowrap" aria-label={t("entities.actions.lifecycle")}>
        {header.publish ? (
          <CanAccess resource={ModuleId.entities} action={ModuleAction.edit}>
            {header.publishFilled ? (
              <HeaderAction primary>
                <Button
                  size="sm"
                  loading={busy}
                  disabled={dirty || savedEmpty}
                  onClick={() => publishConfirm.open(true)}
                >
                  {t("entities.publish")}
                </Button>
              </HeaderAction>
            ) : (
              <Button
                size="sm"
                variant="light"
                loading={busy}
                disabled={dirty || savedEmpty}
                onClick={() => publishConfirm.open(true)}
              >
                {t("entities.publish")}
              </Button>
            )}
          </CanAccess>
        ) : null}
        {header.openVersion ? (
          <CanAccess resource={ModuleId.entities} action={ModuleAction.edit}>
            <Button
              size="sm"
              variant="light"
              loading={busy || openVersionAction.submitting}
              disabled={dirty}
              onClick={() => {
                if (!entityId || !entity) return;
                openVersionAction.run({
                  safety: "confirm",
                  recordName: entity.name,
                  title: t("entities.versions.open.confirmTitle"),
                  consequence: t("entities.versions.open.confirmBody", { name: entity.name }),
                  confirmLabel: t("entities.versions.open"),
                  outcome: t("entities.versions.open.outcome"),
                  execute: async () => {
                    setBusy(true);
                    try {
                      await openVersion(entityId, {});
                      await load();
                    } finally {
                      setBusy(false);
                    }
                  },
                });
              }}
            >
              {t("entities.versions.open")}
            </Button>
          </CanAccess>
        ) : null}
        {header.deprecate ? (
          <CanAccess resource={ModuleId.entities} action={ModuleAction.edit}>
            <Button
              size="sm"
              variant="light"
              color="red"
              loading={busy || lifecycle.isSubmitting("deprecate")}
              onClick={onDeprecate}
            >
              {t("entities.deprecate")}
            </Button>
          </CanAccess>
        ) : null}
      </Group>
  ) : null;
  const standardActions = header.standard ? (
      <Group gap="xs" wrap="nowrap" aria-label={t("entities.actions.standard")}>
        {header.edit ? (
          <CanAccess resource={ModuleId.entities} action={ModuleAction.edit}>
            <Button
              component={ConsoleLink}
              href={entityEditHref(entityId ?? "", tab)}
              size="sm"
              variant="light"
            >
              {t("actions.edit")}
            </Button>
          </CanAccess>
        ) : null}
        {header.deleteEntity ? (
          <CanAccess resource={ModuleId.entities} action={ModuleAction.delete}>
            <Button
              size="sm"
              color="red"
              variant="light"
              loading={lifecycle.isSubmitting("delete")}
              onClick={onDeleteEntity}
            >
              {t("actions.delete")}
            </Button>
          </CanAccess>
        ) : null}
        {header.cancel ? (
          <Button
            component={ConsoleLink}
            href={
              mode === "create"
                ? "/console/entities"
                : entityDetailHref(entityId ?? "", tab)
            }
            variant="default"
            size="sm"
          >
            {t("common.cancel")}
          </Button>
        ) : null}
        {header.cancel ? (
          <HeaderAction primary>
            <Button
              type="submit"
              form={ENTITY_RECORD_FORM_ID}
              size="sm"
              loading={form.submitting}
              disabled={attributeEditorOpen}
            >
              {mode === "create"
                ? t("entities.create.submit")
                : t("entities.edit.submit")}
            </Button>
          </HeaderAction>
        ) : null}
      </Group>
  ) : null;

  const headerActions =
    header.clusters.length === 0 ? undefined : (
      <HeaderActions
        navigation={navigationActions}
        lifecycle={lifecycleActions}
        standard={standardActions}
      />
    );

  return (
    <EntityTabs
      value={tab}
      onChange={selectTab}
        overview={
          <Stack>
            {entity ? (
              <EntityOverviewTab
                entity={entity}
                formatInstant={formatInstant}
                onOpenJob={openJob}
              />
            ) : null}
            <EntityIdentityFields
              form={form}
              tableName={
                mode === "create"
                  ? { mode: "create" }
                  : {
                      mode: "readonly",
                      value: entity?.table_name ?? form.values.table_name,
                    }
              }
              editable={fieldsWritable}
            />
            {entity?.current_version?.publish_status === "unpublished" &&
            entity.effective_change_log ? (
              <EntityChangeLogEffectiveFacts facts={entity.effective_change_log} />
            ) : null}
            <EntityChangeLogFields form={form} editable={fieldsWritable} />
            <EntityTagsControl
              ref={tagsControl}
              mode={mode}
              entityId={entityId}
              tags={entity?.tags ?? EMPTY_TAGS}
              tagRevision={entity?.tag_revision ?? 1}
              editable={
                Boolean(canWrite?.can) &&
                (mode === "create" || (entity != null && !entity.deprecated_at))
              }
              onDraftChange={mode === "create" ? setTagDraft : undefined}
              onSaved={(next) => {
                setEntity((current) =>
                  current
                    ? {
                        ...current,
                        tags: next.tags,
                        tag_revision: next.tag_revision,
                      }
                    : current,
                );
              }}
            />
          </Stack>
        }
        attributes={
          <EntityAttributesTab
            form={form}
            canWrite={fieldsWritable}
            selfEntityId={entity?.id ?? null}
            hintKey={
              mode === "create" ? "entities.create.attributesHint" : undefined
            }
            onEditingChange={setAttributeEditorOpen}
            reveal={attributeReveal}
          />
        }
        versions={
          mode === "create" || !entity ? (
            <EmptyState message={t("entities.create.versionsUnavailable")} />
          ) : (
            <EntityVersionsTab
              entity={entity}
              versions={versions}
              canDropTable={canDropTable}
              busy={busy}
              formatInstant={formatInstant}
              onOpenJob={openJob}
              onViewError={(err) =>
                notifyError(err, t("entities.versions.view.failed"))
              }
              onDrop={(version) => dropConfirm.open(version)}
            />
          )
        }
        showAccess={mode !== "create" && canAccess}
        showData={mode !== "create" && canData}
        showChangeLog={mode !== "create" && canData && recordingOn}
        access={
          entityId ? (
            <EntityAccessTab entityId={entityId} canPreviewRows={canData} />
          ) : null
        }
        data={
          entity ? (
            <EntityDataBrowser
              tableName={entity.table_name}
              physicalHidden={Boolean(
                entity.ever_published && entity.current_version?.table_name == null
              )}
              active={tab === "data"}
            />
          ) : null
        }
        changeLog={
          entityId ? (
            <EntityChangeLogTab
              entityId={entityId}
              active={tab === "change_log"}
              formatInstant={formatInstant}
            />
          ) : null
        }
    >
      {({ list, panels }) => (
    <PageChrome
      title={title}
      recordTitle={recordTitle}
      recent={
        recordTitle && entity
          ? { moduleId: "entities", title: entity.name }
          : undefined
      }
      titleExtra={entity ? <EntityStatusBadge entity={entity} /> : undefined}
      actions={headerActions}
      tabs={list}
    >
      {mode === "show" ? (
        <Stack>{panels}</Stack>
      ) : (
        <form
          id={ENTITY_RECORD_FORM_ID}
          noValidate
          onSubmit={(event) => {
            if (attributeEditorOpen) {
              event.preventDefault();
              return;
            }
            form.onSubmit(
              (values) => submit(values),
              (errors) => {
                const next = createFormErrorTab(errors);
                selectTab(next);
                if (next !== "attributes") return;
                const index = firstAttributeErrorIndex(errors);
                if (index != null) {
                  setAttributeReveal({ index, nonce: Date.now() });
                }
              },
            )(event);
          }}
        >
          <FormErrorSummary failure={saveFailure} />
          <Stack>{panels}</Stack>
        </form>
      )}

      {entity ? (
        <>
          {openVersionAction.dialog}
          <EntityPublishConfirm
            opened={publishConfirm.opened}
            onClose={publishConfirm.close}
            entityId={entity.id}
            versionId={current?.id}
            name={entity.name}
            everPublished={entity.ever_published}
            loading={busy}
            onConfirm={() => void confirmPublish()}
          />
          {lifecycle.dialog}
          <ConfirmActionModal
            opened={dropConfirm.opened}
            onClose={dropConfirm.close}
            title={t("entities.drop.confirmTitle")}
            body={t("entities.drop.confirmBody", {
              table: dropConfirm.pending?.table_name ?? "",
            })}
            confirmColor="red"
            loading={busy}
            confirmLabel={t("entities.drop")}
            onConfirm={() => void confirmDrop()}
          />
          <JobDetailModal
            jobId={jobId}
            opened={jobOpened}
            onClose={() => setJobOpened(false)}
            onChanged={() => void load()}
          />
        </>
      ) : null}
    </PageChrome>
      )}
    </EntityTabs>
  );
}

function EntityChangeLogEffectiveFacts({ facts }: { facts: EffectiveChangeLog }) {
  const t = useTranslate();
  const retention =
    facts.retention_days == null
      ? t("entities.fields.changeLogRetentionNever")
      : facts.retention_days;
  return (
    <>
      <DisplayField
        label={t("entities.fields.changeLogEffective")}
        value={facts.enabled ? t("form.value.yes") : t("form.value.no")}
      />
      <DisplayField
        label={t("entities.fields.changeLogEffectiveRetention")}
        value={retention}
      />
    </>
  );
}
