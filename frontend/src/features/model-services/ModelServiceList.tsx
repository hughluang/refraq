"use client";

import {
  Button,
  Group,
  Modal,
  Paper,
  Stack,
  Table,
  Text,
} from "@mantine/core";
import { useCan, useNotification, useTranslate } from "@refinedev/core";
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { CreateListAction } from "@/components/access/CreateListAction";
import { ListTable } from "@/components/display/ListTable";
import { RecordReference } from "@/components/display/RecordReference";
import { RowActions } from "@/components/display/RowActions";
import { DisplayField } from "@/components/display/DisplayField";
import { Instant } from "@/components/display/Instant";
import { StatusBadge } from "@/components/display/StatusBadge";
import {
  presentIndexStatus,
  presentModelServiceOpen,
  presentModelServiceUse,
} from "@/components/display/statusTone";
import { Callout } from "@/components/feedback/Callout";
import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import { PageChrome } from "@/components/layout/PageChrome";
import { PageTabs } from "@/components/layout/consoleTabs";
import { useConsoleTab } from "@/components/layout/consoleTabs";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import { runSchedule } from "@/features/schedules/api";
import {
  activateModelService,
  cleanupEmbeddingPurpose,
  closeEmbeddingPurpose,
  createModelService,
  forceEmbeddingGeneration,
  deleteModelService,
  getEmbeddingPurpose,
  getModelService,
  openEmbeddingPurpose,
  patchModelService,
  testModelService,
  listModelServices,
} from "@/features/model-services/api";
import {
  ModelServiceForm,
  servicePayload,
} from "@/features/model-services/ModelServiceForm";
import type {
  CatalogIndexState,
  EmbedSchedule,
  EntityIndexState,
  ModelService,
  ModelServiceFormValues,
  ModelServiceTestResult,
  PurposeState,
} from "@/features/model-services/types";
import { useConfirmAction } from "@/hooks/useConfirmAction";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { useListQuery } from "@/hooks/useListQuery";
import { problemMessage } from "@/lib/problem";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;

const ENTITY_INDEX_LABEL: Record<string, string> = {
  none: "modelServices.entity.index.none",
  indexing: "modelServices.entity.index.indexing",
  ready: "modelServices.entity.index.ready",
  failed: "modelServices.entity.index.failed",
};

function presentEntityIndex(status: string) {
  return {
    tone: presentIndexStatus(status).tone,
    labelKey: ENTITY_INDEX_LABEL[status] ?? "status.unknown",
  };
}

function ScheduleSummary({ schedule }: { schedule: EmbedSchedule | null }) {
  const t = useTranslate();
  if (!schedule) {
    return <Text size="sm">{t("modelServices.index.scheduleMissing")}</Text>;
  }
  const cadence =
    schedule.cron ??
    (schedule.interval_seconds != null
      ? t("modelServices.index.scheduleInterval", {
          seconds: schedule.interval_seconds,
        })
      : t("modelServices.index.scheduleMissing"));
  return (
    <Stack gap={2}>
      <Text size="sm">
        {schedule.enabled
          ? t("modelServices.index.scheduleEnabled")
          : t("modelServices.index.scheduleDisabled")}
      </Text>
      <Text size="sm">{cadence}</Text>
      <Text size="sm">
        {t("modelServices.index.scheduleNext")}:{" "}
        <Instant value={schedule.next_run_at} />
      </Text>
    </Stack>
  );
}

function IndexStatusPanel({
  titleId,
  title,
  badge,
  generation,
  coverage,
  progress,
  failureSummary,
  schedule,
  rebuildOwed,
  readyNote,
  rebuild,
}: {
  titleId: string;
  title: string;
  badge: { tone: ReturnType<typeof presentIndexStatus>["tone"]; labelKey: string };
  generation: number | null;
  coverage: ReactNode;
  progress: string | null;
  failureSummary: string | null;
  schedule: EmbedSchedule | null;
  rebuildOwed: boolean;
  readyNote?: string | null;
  rebuild?: { label: string; onClick: () => void } | null;
}) {
  const t = useTranslate();
  return (
    <Paper withBorder p="md" component="section" aria-labelledby={titleId}>
      <Stack gap="sm">
        <Group gap="xs">
          <Text id={titleId} fw={600}>
            {title}
          </Text>
          <StatusBadge tone={badge.tone} labelKey={badge.labelKey} />
        </Group>
        {readyNote ? <Text size="sm">{readyNote}</Text> : null}
        <DisplayField
          label={t("modelServices.index.generation")}
          value={generation ?? t("modelServices.index.generationNone")}
        />
        <DisplayField label={t("modelServices.index.coverage")} value={coverage} />
        {progress ? (
          <DisplayField label={t("modelServices.index.progress")} value={progress} />
        ) : null}
        {failureSummary ? (
          <DisplayField
            label={t("modelServices.index.failure")}
            value={failureSummary}
          />
        ) : null}
        <DisplayField
          label={t("modelServices.index.schedule")}
          value={<ScheduleSummary schedule={schedule} />}
        />
        {rebuildOwed ? (
          <Text size="sm">{t("modelServices.index.rebuildOwed")}</Text>
        ) : null}
        {rebuild ? (
          <Group>
            <Button size="compact-sm" variant="light" onClick={rebuild.onClick}>
              {rebuild.label}
            </Button>
          </Group>
        ) : null}
      </Stack>
    </Paper>
  );
}

function CatalogCoverage({ index }: { index: CatalogIndexState }) {
  const t = useTranslate();
  return (
    <Stack gap={2}>
      <Text size="sm">
        {t("modelServices.catalog.coverage.objects", {
          written: index.coverage.objects_written,
          failed: index.coverage.objects_failed,
          attempted: index.coverage.objects_attempted,
        })}
      </Text>
      <Text size="sm">
        {t("modelServices.catalog.coverage.columns", {
          written: index.coverage.columns_written,
          failed: index.coverage.columns_failed,
          attempted: index.coverage.columns_attempted,
        })}
      </Text>
    </Stack>
  );
}

function EntityCoverage({ index }: { index: EntityIndexState }) {
  const t = useTranslate();
  return t("modelServices.entity.coverage", {
    written: index.coverage.written,
    failed: index.coverage.failed,
    attempted: index.coverage.attempted,
  });
}

export function ModelServiceList() {
  const t = useTranslate();
  const { open } = useNotification();
  const { data: canWrite } = useCan({
    resource: ModuleId.modelServices,
    action: ModuleAction.edit,
  });
  const { data: canDelete } = useCan({
    resource: ModuleId.modelServices,
    action: ModuleAction.delete,
  });

  const [purpose, setPurpose] = useState<PurposeState | null>(null);
  const [fetchedInUse, setFetchedInUse] = useState<ModelService | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<ModelService | undefined>();
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<ModelServiceTestResult | null>(
    null,
  );
  const [opening, setOpening] = useState(false);
  const [forcing, setForcing] = useState(false);
  const [closing, setClosing] = useState(false);
  const [cleaning, setCleaning] = useState(false);
  const [rebuilding, setRebuilding] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [activatingId, setActivatingId] = useState<string | null>(null);
  const serviceTabs = useMemo(
    () => [{ value: "configure" }, { value: "status" }],
    [],
  );
  const { value: activeTab, setTab } = useConsoleTab(serviceTabs);
  const openConfirm = useConfirmAction<true>();
  const forceConfirm = useConfirmAction<true>();
  const closeConfirm = useConfirmAction<true>();
  const cleanupConfirm = useConfirmAction<true>();
  const rebuildConfirm = useConfirmAction<"catalog" | "entity">();
  const rebuildCopy = useRef<"catalog" | "entity">("catalog");
  if (rebuildConfirm.pending != null) {
    rebuildCopy.current = rebuildConfirm.pending;
  }
  const rebuildKind = rebuildConfirm.pending ?? rebuildCopy.current;
  const deleteConfirm = useConfirmAction<ModelService>();
  const activateConfirm = useConfirmAction<ModelService>();
  const { data: canListSchedules } = useCan({
    resource: ModuleId.schedules,
    action: ModuleAction.list,
  });

  const query = useListQuery({ search: false });
  const fetchPage = useCallback(
    (page: PageQuery) => listModelServices(page),
    [],
  );
  const list = useConsolePagedList({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
    page: query.page,
    onPageChange: query.setPage,
  });
  const { items, reload } = list;
  const showActions = Boolean(canWrite?.can || canDelete?.can);

  const notifyError = (err: unknown, fallback: string) => {
    open?.({
      type: "error",
      message: problemMessage(t, err, fallback),
    });
  };

  const reloadPurpose = async () => {
    const next = await getEmbeddingPurpose();
    setPurpose(next);
    return next;
  };

  useEffect(() => {
    void reloadPurpose().catch((err: unknown) => {
      notifyError(err, t("common.error.loadFailed"));
    });
    // Purpose is loaded once on mount; list reload handles later refreshes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const listedInUse =
    items.find((row) => row.id === purpose?.in_use_id) ?? null;
  const listedInUseId = listedInUse?.id ?? null;

  useEffect(() => {
    const id = purpose?.in_use_id;
    if (!id || listedInUseId) {
      setFetchedInUse(null);
      return;
    }
    let cancelled = false;
    getModelService(id)
      .then((row) => {
        if (!cancelled) setFetchedInUse(row);
      })
      .catch(() => {
        if (!cancelled) setFetchedInUse(null);
      });
    return () => {
      cancelled = true;
    };
  }, [purpose?.in_use_id, listedInUseId]);

  const refreshAll = async () => {
    await Promise.all([reload(), reloadPurpose()]);
  };

  const save = async (values: ModelServiceFormValues) => {
    const payload = servicePayload(values);
    if (editing) {
      await patchModelService(editing.id, payload);
      open?.({
        type: "success",
        message: t("modelServices.update.success"),
      });
    } else {
      await createModelService(payload);
      open?.({
        type: "success",
        message: t("modelServices.create.success"),
      });
    }
    setFormOpen(false);
    setEditing(undefined);
    await refreshAll();
  };

  const runTest = async (row: ModelService) => {
    setTestingId(row.id);
    try {
      setTestResult(await testModelService(row.id));
    } catch (err) {
      notifyError(err, t("modelServices.test.failed"));
    } finally {
      setTestingId(null);
    }
  };

  const openActivate = async (row: ModelService) => {
    setActivatingId(row.id);
    try {
      await testModelService(row.id);
      activateConfirm.open(row);
    } catch (err) {
      notifyError(err, t("modelServices.test.failed"));
    } finally {
      setActivatingId(null);
    }
  };

  const confirmActivate = async () => {
    const pending = activateConfirm.pending;
    if (!pending) return;
    setActivatingId(pending.id);
    try {
      await activateModelService(pending.id);
      open?.({
        type: "success",
        message: t("modelServices.activate.success"),
      });
      activateConfirm.close();
      await refreshAll();
    } catch (err) {
      notifyError(err, t("common.error.loadFailed"));
    } finally {
      setActivatingId(null);
    }
  };

  const confirmForce = async () => {
    setForcing(true);
    try {
      await forceEmbeddingGeneration();
      open?.({
        type: "success",
        message: t("modelServices.forceGeneration.success"),
      });
      forceConfirm.close();
      await refreshAll();
    } catch (err) {
      notifyError(err, t("common.error.loadFailed"));
    } finally {
      setForcing(false);
    }
  };

  const confirmClose = async () => {
    setClosing(true);
    try {
      await closeEmbeddingPurpose();
      open?.({ type: "success", message: t("modelServices.close.success") });
      closeConfirm.close();
      await refreshAll();
    } catch (err) {
      notifyError(err, t("common.error.loadFailed"));
    } finally {
      setClosing(false);
    }
  };

  const confirmOpen = async () => {
    setOpening(true);
    try {
      await openEmbeddingPurpose();
      open?.({ type: "success", message: t("modelServices.open.success") });
      openConfirm.close();
      await refreshAll();
    } catch (err) {
      notifyError(err, t("common.error.loadFailed"));
    } finally {
      setOpening(false);
    }
  };

  const confirmRebuild = async () => {
    const pending = rebuildConfirm.pending;
    if (!pending || !purpose) return;
    const scheduleId =
      pending === "catalog"
        ? purpose.embed_schedule?.id
        : purpose.entity_index.schedule?.id;
    if (!scheduleId) return;
    setRebuilding(true);
    try {
      await runSchedule(scheduleId);
      open?.({
        type: "success",
        message: t("modelServices.rebuild.success"),
      });
      rebuildConfirm.close();
      await refreshAll();
    } catch (err) {
      notifyError(err, t("common.error.loadFailed"));
    } finally {
      setRebuilding(false);
    }
  };

  const confirmCleanup = async () => {
    setCleaning(true);
    try {
      await cleanupEmbeddingPurpose();
      open?.({ type: "success", message: t("modelServices.cleanup.success") });
      cleanupConfirm.close();
      await refreshAll();
    } catch (err) {
      notifyError(err, t("common.error.loadFailed"));
    } finally {
      setCleaning(false);
    }
  };

  const confirmDelete = async () => {
    const pending = deleteConfirm.pending;
    if (!pending) return;
    setDeleting(true);
    try {
      await deleteModelService(pending.id);
      open?.({ type: "success", message: t("modelServices.delete.success") });
      deleteConfirm.close();
      await refreshAll();
    } catch (err) {
      notifyError(err, t("common.error.loadFailed"));
    } finally {
      setDeleting(false);
    }
  };

  const createAction = (
    <CreateListAction
      resource={ModuleId.modelServices}
      onClick={() => {
        setEditing(undefined);
        setFormOpen(true);
      }}
    >
      {t("modelServices.create")}
    </CreateListAction>
  );

  const canCleanup = Boolean(purpose?.closed || !purpose?.in_use_id);
  const canRebuild = Boolean(showActions && canListSchedules?.can);
  const inUseService = listedInUse ?? fetchedInUse;
  const showScheduleLink = Boolean(
    canListSchedules?.can && purpose?.embed_schedule,
  );

  return (
    <PageTabs
      value={activeTab}
      onChange={setTab}
      tabs={[
        {
          value: "configure",
          label: t("modelServices.tabs.configure"),
          panel: (
          <Stack gap="md">
            <Group justify="flex-end">{createAction}</Group>
            <ListTable
              list={list}
              columnCount={showActions ? 7 : 6}
              emptyMessage={t("modelServices.empty")}
              emptyAction={createAction}
              head={
                <Table.Tr>
                  <Table.Th>{t("modelServices.fields.display_name")}</Table.Th>
                  <Table.Th>{t("modelServices.fields.protocol")}</Table.Th>
                  <Table.Th>{t("modelServices.fields.url")}</Table.Th>
                  <Table.Th>{t("modelServices.fields.model")}</Table.Th>
                  <Table.Th>{t("modelServices.fields.in_use")}</Table.Th>
                  <Table.Th>{t("modelServices.fields.has_secret")}</Table.Th>
                  {showActions ? (
                    <Table.Th>{t("modelServices.fields.actions")}</Table.Th>
                  ) : null}
                </Table.Tr>
              }
            >
              {items.map((row) => (
                <Table.Tr key={row.id}>
                  <Table.Td>
                    <RecordReference name={row.display_name} recordKey={row.model} />
                  </Table.Td>
                  <Table.Td>{t(`modelServices.protocol.${row.protocol}`)}</Table.Td>
                  <Table.Td>
                    <Text size="sm" lineClamp={1}>
                      {row.url}
                    </Text>
                  </Table.Td>
                  <Table.Td>{row.model}</Table.Td>
                  <Table.Td>
                    <StatusBadge
                      tone={presentModelServiceUse(row.in_use).tone}
                      labelKey={presentModelServiceUse(row.in_use).labelKey}
                    />
                  </Table.Td>
                  <Table.Td>
                    {row.has_secret
                      ? t("modelServices.status.secretSet")
                      : t("modelServices.status.secretNone")}
                  </Table.Td>
                  {showActions ? (
                    <Table.Td>
                      <RowActions
                        recordName={row.display_name}
                        verbs={[
                          {
                            key: "edit",
                            label: t("actions.edit"),
                            hidden: !canWrite?.can,
                            safety: "immediate",
                            onClick: () => {
                              setEditing(row);
                              setFormOpen(true);
                            },
                          },
                          {
                            key: "test",
                            label: t("modelServices.test"),
                            hidden: !canWrite?.can,
                            disabledReason:
                              testingId === row.id
                                ? t("modelServices.test")
                                : undefined,
                            safety: "immediate",
                            onClick: () => void runTest(row),
                          },
                          {
                            key: "activate",
                            label: t("modelServices.activate"),
                            hidden: !canWrite?.can,
                            disabledReason: row.in_use
                              ? t("modelServices.activate.inUse")
                              : activatingId === row.id
                                ? t("modelServices.activate")
                                : undefined,
                            safety: "confirm",
                            onClick: () => void openActivate(row),
                          },
                          {
                            key: "delete",
                            label: t("actions.delete"),
                            color: "red",
                            hidden: !canDelete?.can,
                            safety: "confirm",
                            onClick: () => deleteConfirm.open(row),
                          },
                        ]}
                      />
                    </Table.Td>
                  ) : null}
                </Table.Tr>
              ))}
            </ListTable>
          </Stack>
          ),
        },
        {
          value: "status",
          label: t("modelServices.tabs.status"),
          panel: purpose ? (
          <Stack gap="md">
            <Paper
              withBorder
              p="md"
              component="section"
              aria-labelledby="model-service-shared"
            >
              <Stack gap="sm">
                <Group justify="space-between" align="center">
                  <Group gap="xs" align="center">
                    <Text id="model-service-shared" fw={600}>
                      {t("modelServices.shared.title")}
                    </Text>
                    <StatusBadge
                      tone={presentModelServiceOpen(purpose.closed).tone}
                      labelKey={presentModelServiceOpen(purpose.closed).labelKey}
                    />
                  </Group>
                  {showActions || showScheduleLink ? (
                    <Group gap="xs">
                      {showActions && purpose.in_use_id ? (
                        <Button
                          size="compact-sm"
                          variant="light"
                          onClick={() => forceConfirm.open(true)}
                        >
                          {t("modelServices.forceGeneration")}
                        </Button>
                      ) : null}
                      {showActions ? (
                        purpose.closed ? (
                          <Button
                            size="compact-sm"
                            variant="light"
                            disabled={!purpose.in_use_id}
                            onClick={() => openConfirm.open(true)}
                          >
                            {t("modelServices.open")}
                          </Button>
                        ) : (
                          <Button
                            size="compact-sm"
                            variant="light"
                            onClick={() => closeConfirm.open(true)}
                          >
                            {t("modelServices.close")}
                          </Button>
                        )
                      ) : null}
                      {showActions ? (
                        <Button
                          size="compact-sm"
                          variant="light"
                          disabled={!canCleanup}
                          onClick={() => cleanupConfirm.open(true)}
                        >
                          {t("modelServices.cleanup")}
                        </Button>
                      ) : null}
                      {showScheduleLink ? (
                        <Button
                          size="compact-sm"
                          variant="default"
                          component={ConsoleLink}
                          href="/console/schedules"
                        >
                          {t("schedules.title")}
                        </Button>
                      ) : null}
                    </Group>
                  ) : null}
                </Group>
                {inUseService ? (
                  <Stack gap="sm">
                    <DisplayField
                      label={t("modelServices.fields.url")}
                      value={inUseService.url}
                    />
                    <DisplayField
                      label={t("modelServices.fields.model")}
                      value={inUseService.model}
                    />
                    <DisplayField
                      label={t("modelServices.fields.timeout_sec")}
                      value={inUseService.timeout_sec}
                    />
                    <DisplayField
                      label={t("modelServices.fields.batch_limit")}
                      value={inUseService.batch_limit}
                    />
                    <DisplayField
                      label={t("modelServices.fields.has_secret")}
                      value={
                        inUseService.has_secret
                          ? t("modelServices.status.secretSet")
                          : t("modelServices.status.secretNone")
                      }
                    />
                  </Stack>
                ) : purpose.in_use_id ? null : (
                  <Text size="sm">{t("modelServices.shared.noService")}</Text>
                )}
                {purpose.closed ? (
                  <Callout tone="notice" title={t("modelServices.closed.noteTitle")}>
                    {t("modelServices.closed.note")}
                  </Callout>
                ) : null}
              </Stack>
            </Paper>
            <IndexStatusPanel
              titleId="model-service-catalog-index"
              title={t("modelServices.catalog.title")}
              badge={presentIndexStatus(purpose.catalog_index.index_status)}
              generation={purpose.catalog_index.generation_last_swept}
              coverage={<CatalogCoverage index={purpose.catalog_index} />}
              progress={purpose.catalog_index.progress}
              failureSummary={purpose.catalog_index.failure_summary}
              schedule={purpose.embed_schedule}
              rebuildOwed={purpose.catalog_index.rebuild_owed}
              rebuild={
                canRebuild && purpose.embed_schedule
                  ? {
                      label: t("modelServices.rebuild.catalog"),
                      onClick: () => rebuildConfirm.open("catalog"),
                    }
                  : null
              }
            />
            <IndexStatusPanel
              titleId="model-service-entity-index"
              title={t("modelServices.entity.title")}
              badge={presentEntityIndex(purpose.entity_index.index_status)}
              generation={purpose.entity_index.generation}
              coverage={<EntityCoverage index={purpose.entity_index} />}
              progress={purpose.entity_index.progress}
              failureSummary={purpose.entity_index.failure_summary}
              schedule={purpose.entity_index.schedule}
              rebuildOwed={purpose.entity_index.rebuild_owed}
              readyNote={
                purpose.entity_index.ready
                  ? t("modelServices.entity.readyNote")
                  : null
              }
              rebuild={
                canRebuild && purpose.entity_index.schedule
                  ? {
                      label: t("modelServices.rebuild.entity"),
                      onClick: () => rebuildConfirm.open("entity"),
                    }
                  : null
              }
            />
          </Stack>
          ) : (
            <Stack gap="md" />
          ),
        },
      ]}
    >
      {({ list, panels }) => (
    <PageChrome
      title={t("modelServices.title")}
      description={t("modelServices.description")}
      tabs={list}
    >
      {panels}

      <Modal.Stack>
        <ModelServiceForm
          key={editing?.id ?? "create"}
          opened={formOpen}
          service={editing}
          onSubmit={save}
          onClose={() => {
            setFormOpen(false);
            setEditing(undefined);
          }}
        />

        <Modal
          stackId="model-service-test"
          opened={testResult !== null}
          onClose={() => setTestResult(null)}
          title={t("modelServices.test")}
          size="md"
        >
          {testResult ? (
            <Stack gap="sm">
              <Text size="sm">
                {t("modelServices.test.model")}: {testResult.model}
              </Text>
              <Text size="sm">
                {t("modelServices.test.dimension")}: {testResult.dimension}
              </Text>
              <Text size="sm">
                {t("modelServices.test.outputDim", {
                  dim: testResult.output_dim,
                })}
              </Text>
              <Text size="sm" c="dimmed">
                {t("modelServices.test.timeout", {
                  sec: testResult.timeout_sec,
                })}
              </Text>
              <Text size="sm" c="dimmed">
                {t("modelServices.test.elapsed", {
                  ms: testResult.elapsed_ms,
                })}
              </Text>
            </Stack>
          ) : null}
        </Modal>

        <ConfirmActionModal
          stackId="model-service-activate"
          opened={activateConfirm.opened}
          onClose={activateConfirm.close}
          title={t("modelServices.activate.confirmTitle")}
          body={t("modelServices.activate.confirmBody")}
          loading={activatingId !== null}
          onConfirm={() => void confirmActivate()}
        />

        <ConfirmActionModal
          stackId="model-service-force-generation"
          opened={forceConfirm.opened}
          onClose={forceConfirm.close}
          title={t("modelServices.forceGeneration.confirmTitle")}
          body={t("modelServices.forceGeneration.confirmBody")}
          loading={forcing}
          onConfirm={() => void confirmForce()}
        />

        <ConfirmActionModal
          stackId="model-service-close"
          opened={closeConfirm.opened}
          onClose={closeConfirm.close}
          title={t("modelServices.close.confirmTitle")}
          body={t("modelServices.close.confirmBody")}
          loading={closing}
          onConfirm={() => void confirmClose()}
        />

        <ConfirmActionModal
          stackId="model-service-open"
          opened={openConfirm.opened}
          onClose={openConfirm.close}
          title={t("modelServices.open.confirmTitle")}
          body={t("modelServices.open.confirmBody")}
          loading={opening}
          onConfirm={() => void confirmOpen()}
        />

        <ConfirmActionModal
          stackId="model-service-rebuild"
          opened={rebuildConfirm.opened}
          onClose={rebuildConfirm.close}
          title={t(
            rebuildKind === "entity"
              ? "modelServices.rebuild.entityTitle"
              : "modelServices.rebuild.catalogTitle",
          )}
          body={t(
            rebuildKind === "entity"
              ? "modelServices.rebuild.entityBody"
              : "modelServices.rebuild.catalogBody",
          )}
          loading={rebuilding}
          onConfirm={() => void confirmRebuild()}
        />

        <ConfirmActionModal
          stackId="model-service-cleanup"
          opened={cleanupConfirm.opened}
          onClose={cleanupConfirm.close}
          title={t("modelServices.cleanup.confirmTitle")}
          body={t("modelServices.cleanup.confirmBody")}
          confirmColor="red"
          loading={cleaning}
          onConfirm={() => void confirmCleanup()}
        />

        <ConfirmActionModal
          stackId="model-service-delete"
          opened={deleteConfirm.opened}
          onClose={deleteConfirm.close}
          title={t("modelServices.delete.confirmTitle")}
          body={
            deleteConfirm.pending?.in_use
              ? t("modelServices.delete.confirmInUse")
              : t("modelServices.delete.confirmBody")
          }
          confirmColor="red"
          loading={deleting}
          onConfirm={() => void confirmDelete()}
        />
      </Modal.Stack>
    </PageChrome>
      )}
    </PageTabs>
  );
}
