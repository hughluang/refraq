"use client";

import { Button, Divider, Group, Stack } from "@mantine/core";
import { useForm } from "@mantine/form";
import {
  CanAccess,
  useCan,
  useNotification,
  usePermissions,
  useTranslate,
} from "@refinedev/core";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState, type ReactNode } from "react";

import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import { EmptyState } from "@/components/feedback/EmptyState";
import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { PageError } from "@/components/feedback/PageError";
import { PageChrome } from "@/components/layout/PageChrome";
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
import { EntityDataBrowser } from "@/features/entities/EntityDataBrowser";
import { EntityIdentityFields } from "@/features/entities/EntityIdentityFields";
import { EntityOverviewTab } from "@/features/entities/EntityOverviewTab";
import { EntityTabs } from "@/features/entities/EntityTabs";
import { EntityVersionsTab } from "@/features/entities/EntityVersionsTab";
import { EntityStatusBadge } from "@/features/entities/EntityStatusBadge";
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
import { ACCESS_MANAGE_PERMISSION, DATA_READ_PERMISSION, DROP_TABLE_PERMISSION } from "@/features/entities/constants";
import {
  createFormErrorTab,
  entityDetailHref,
  entityEditHref,
  entityRecordHref,
  isEntityDetailTab,
  parseEntityDetailTab,
  replaceEntityLocation,
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
  EntityRecordFormValues,
  EntityVersion,
} from "@/features/entities/types";
import { JobDetailModal } from "@/features/jobs/JobDetailModal";
import { LEAVE_GUARD_ALLOW } from "@/hooks/leaveGuard";
import { useConfirmAction } from "@/hooks/useConfirmAction";
import { useFormatInstant } from "@/hooks/useFormatInstant";
import { useLeaveGuard } from "@/hooks/useLeaveGuard";
import { problemMessage } from "@/lib/problem";

export type { EntityRecordMode };

type Props =
  | { mode: "create" }
  | { mode: "show" | "edit"; entityId: string };

export function EntityRecord(props: Props) {
  const mode = props.mode;
  const entityId = props.mode === "create" ? undefined : props.entityId;
  const t = useTranslate();
  const { open } = useNotification();
  const router = useRouter();
  const searchParams = useSearchParams();
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

  const rawTab = searchParams.get("tab");
  const [tab, setTab] = useState(() => parseEntityDetailTab(rawTab));

  const [entity, setEntity] = useState<BusinessEntity | null>(null);
  const [versions, setVersions] = useState<EntityVersion[]>([]);
  const [current, setCurrent] = useState<EntityVersion | null>(null);
  const [loading, setLoading] = useState(mode !== "create");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobOpened, setJobOpened] = useState(false);

  const deleteEntityConfirm = useConfirmAction<true>();
  const dropConfirm = useConfirmAction<EntityVersion>();
  const publishConfirm = useConfirmAction<true>();
  const deprecateConfirm = useConfirmAction<true>();

  const [attributeEditorOpen, setAttributeEditorOpen] = useState(false);
  const [attributeReveal, setAttributeReveal] = useState<AttributeReveal | null>(
    null,
  );

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

  const form = useForm<EntityRecordFormValues>({
    initialValues: {
      table_name: "",
      name: "",
      description: "",
      attributes: [],
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

  const leaveGuard = useLeaveGuard({
    enabled: mode !== "show" && form.isDirty(),
    message: t("common.leaveUnsaved"),
  });

  const load = useCallback(async () => {
    if (!entityId) return;
    setLoading(true);
    setError(null);
    try {
      const [entityRes, versionsRes] = await Promise.all([
        getEntity(entityId),
        listVersions(entityId, { limit: 200 }),
      ]);
      const loaded = entityRes.entity;
      setEntity(loaded);
      setVersions(versionsRes.items);
      const currentId = loaded.current_version?.id;
      let version: EntityVersion | null = null;
      if (currentId) {
        const versionRes = await getVersion(entityId, currentId);
        version = versionRes.version;
        setCurrent(version);
      } else {
        setCurrent(null);
      }
      form.setValues({
        table_name: loaded.table_name,
        name: loaded.name,
        description: loaded.description,
        attributes: version ? draftsFromVersion(version) : [],
      });
      form.resetDirty();
    } catch (err) {
      setError(problemMessage(t, err, String(err)));
      setEntity(null);
    } finally {
      setLoading(false);
    }
  }, [entityId]);

  useEffect(() => {
    if (mode === "create") return;
    void load();
  }, [load, mode]);

  useEffect(() => {
    setTab(parseEntityDetailTab(rawTab));
  }, [rawTab]);

  useEffect(() => {
    if (rawTab != null && !isEntityDetailTab(rawTab)) {
      setTab("overview");
      replaceEntityLocation(entityRecordHref(mode, entityId));
    }
  }, [entityId, mode, rawTab]);

  useEffect(() => {
    if (mode !== "edit" || !entityId || !entity) return;
    if (canAuthor(entity)) return;
    router.replace(entityDetailHref(entityId, tab));
  }, [entity, entityId, mode, router, tab]);

  useEffect(() => {
    if (!Array.isArray(permissions) || mode === "create") return;
    const hidden =
      (tab === "access" && !canAccess) || (tab === "data" && !canData);
    if (!hidden) return;
    setTab("overview");
    replaceEntityLocation(entityRecordHref(mode, entityId));
  }, [canAccess, canData, entityId, mode, permissions, tab]);

  const selectTab = (next: typeof tab) => {
    setTab(next);
    replaceEntityLocation(entityRecordHref(mode, entityId, next));
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
    setBusy(true);
    try {
      if (mode === "create") {
        const created = await createEntity({
          table_name: values.table_name.trim(),
          name: values.name.trim(),
          description: values.description.trim(),
          attributes: attributesFromDrafts(values.attributes),
        });
        form.resetDirty();
        leaveGuard.bypass();
        open?.({ type: "success", message: t("entities.create.success") });
        window.location.replace(entityEditHref(created.entity.id, "attributes"));
        return;
      }
      if (mode !== "edit" || !entityId) return;
      await patchEntity(entityId, {
        name: values.name.trim(),
        description: values.description.trim(),
        attributes: attributesFromDrafts(values.attributes),
      });
      form.resetDirty();
      open?.({ type: "success", message: t("entities.update.success") });
      await load();
    } catch (err) {
      notifyError(
        err,
        mode === "create" ? String(err) : t("entities.update.failed"),
      );
    } finally {
      setBusy(false);
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

  const openNextVersion = async () => {
    if (!entityId) return;
    setBusy(true);
    try {
      await openVersion(entityId, {});
      open?.({ type: "success", message: t("entities.versions.open.success") });
      await load();
    } catch (err) {
      notifyError(err, t("entities.versions.open.failed"));
    } finally {
      setBusy(false);
    }
  };

  const confirmDeprecate = async () => {
    if (!entityId) return;
    setBusy(true);
    try {
      await deprecateEntity(entityId);
      deprecateConfirm.close();
      open?.({ type: "success", message: t("entities.deprecate.success") });
      await load();
    } catch (err) {
      notifyError(err, t("entities.deprecate.failed"));
    } finally {
      setBusy(false);
    }
  };

  const confirmDeleteEntity = async () => {
    if (!entityId) return;
    setBusy(true);
    try {
      await deleteEntity(entityId);
      deleteEntityConfirm.close();
      leaveGuard.bypass();
      open?.({ type: "success", message: t("entities.delete.success") });
      router.push("/console/entities");
    } catch (err) {
      notifyError(err, t("entities.delete.failed"));
    } finally {
      setBusy(false);
    }
  };

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
      <PageChrome title={t("entities.title")} description={t("entities.description")}>
        <PageBodySkeleton />
      </PageChrome>
    );
  }

  if (mode !== "create" && (error || !entity)) {
    return (
      <PageChrome title={t("entities.title")} description={t("entities.description")}>
        <PageError
          message={error ?? t("entities.notFound")}
          onRetry={() => void load()}
        />
      </PageChrome>
    );
  }

  if (mode === "edit" && entity && !canAuthor(entity)) {
    return (
      <PageChrome title={t("entities.edit.title")}>
        <PageBodySkeleton rows={5} />
      </PageChrome>
    );
  }

  const writable = entity ? canAuthor(entity) : false;
  const publishing = entity ? isPublishing(entity) : false;
  const deprecated = Boolean(entity?.deprecated_at);
  const dirty = form.isDirty();
  const savedEmpty = (current?.attributes ?? []).length === 0;
  const published = entity?.current_version?.publish_status === "published";
  const title =
    mode === "create"
      ? t("entities.create.title")
      : entity
        ? `${entity.name} · ${entity.table_name}`
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

  const headerActionClusters: ReactNode[] = [];
  if (header.navigation) {
    headerActionClusters.push(
      <Group
        key="navigation"
        gap="xs"
        wrap="nowrap"
        aria-label={t("entities.actions.navigation")}
      >
        <Button
          component={Link}
          href="/console/entities"
          variant="default"
          size="sm"
        >
          {t("entities.backToList")}
        </Button>
        <Button size="sm" variant="light" onClick={() => void load()}>
          {t("jobs.refresh")}
        </Button>
      </Group>,
    );
  }
  if (header.lifecycle) {
    headerActionClusters.push(
      <Group
        key="lifecycle"
        gap="xs"
        wrap="nowrap"
        aria-label={t("entities.actions.lifecycle")}
      >
        {header.publish ? (
          <CanAccess resource={ModuleId.entities} action={ModuleAction.edit}>
            <Button
              size="sm"
              variant={header.publishFilled ? "filled" : "light"}
              loading={busy}
              disabled={dirty || savedEmpty}
              onClick={() => publishConfirm.open(true)}
            >
              {t("entities.publish")}
            </Button>
          </CanAccess>
        ) : null}
        {header.openVersion ? (
          <CanAccess resource={ModuleId.entities} action={ModuleAction.edit}>
            <Button
              size="sm"
              variant="light"
              loading={busy}
              disabled={dirty}
              onClick={() => void openNextVersion()}
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
              loading={busy}
              onClick={() => deprecateConfirm.open(true)}
            >
              {t("entities.deprecate")}
            </Button>
          </CanAccess>
        ) : null}
      </Group>,
    );
  }
  if (header.standard) {
    headerActionClusters.push(
      <Group
        key="standard"
        gap="xs"
        wrap="nowrap"
        aria-label={t("entities.actions.standard")}
      >
        {header.edit ? (
          <CanAccess resource={ModuleId.entities} action={ModuleAction.edit}>
            <Button
              component={Link}
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
              onClick={() => deleteEntityConfirm.open(true)}
            >
              {t("actions.delete")}
            </Button>
          </CanAccess>
        ) : null}
        {header.cancel ? (
          <Button
            component={Link}
            href={
              mode === "create"
                ? "/console/entities"
                : entityDetailHref(entityId ?? "", tab)
            }
            variant="default"
            size="sm"
            data-leave-guard={LEAVE_GUARD_ALLOW}
          >
            {t("common.cancel")}
          </Button>
        ) : null}
        {header.cancel ? (
          <Button
            type="submit"
            form={ENTITY_RECORD_FORM_ID}
            size="sm"
            loading={busy}
            disabled={attributeEditorOpen}
          >
            {mode === "create"
              ? t("entities.create.submit")
              : t("entities.edit.submit")}
          </Button>
        ) : null}
      </Group>,
    );
  }

  const headerActions =
    headerActionClusters.length === 0 ? undefined : (
      <Group gap="xs" wrap="wrap" align="center">
        {headerActionClusters.flatMap((cluster, index) =>
          index === 0
            ? [cluster]
            : [
                <Divider
                  key={`divider-${header.clusters[index]}`}
                  orientation="vertical"
                  h={28}
                />,
                cluster,
              ],
        )}
      </Group>
    );

  const formBody = (
    <Stack>
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
            />
          ) : null
        }
      />
    </Stack>
  );

  return (
    <PageChrome
      title={title}
      titleExtra={entity ? <EntityStatusBadge entity={entity} /> : undefined}
      actions={headerActions}
    >
      {mode === "show" ? (
        formBody
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
              (values) => void submit(values),
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
          {formBody}
        </form>
      )}

      {entity ? (
        <>
          <ConfirmActionModal
            opened={publishConfirm.opened}
            onClose={publishConfirm.close}
            title={t("entities.publish.confirmTitle")}
            body={t(
              entity.ever_published
                ? "entities.publish.confirmBodySuccessor"
                : "entities.publish.confirmBody",
              { name: entity.name },
            )}
            loading={busy}
            confirmLabel={t("entities.publish")}
            onConfirm={() => void confirmPublish()}
          />
          <ConfirmActionModal
            opened={deprecateConfirm.opened}
            onClose={deprecateConfirm.close}
            title={t("entities.deprecate.confirmTitle")}
            body={t("entities.deprecate.confirmBody", { name: entity.name })}
            confirmColor="red"
            loading={busy}
            confirmLabel={t("entities.deprecate")}
            onConfirm={() => void confirmDeprecate()}
          />
          <ConfirmActionModal
            opened={deleteEntityConfirm.opened}
            onClose={deleteEntityConfirm.close}
            title={t("entities.delete.confirmTitle")}
            body={t("entities.delete.confirmBody", { name: entity.name })}
            confirmColor="red"
            loading={busy}
            confirmLabel={t("actions.delete")}
            onConfirm={() => void confirmDeleteEntity()}
          />
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
  );
}
