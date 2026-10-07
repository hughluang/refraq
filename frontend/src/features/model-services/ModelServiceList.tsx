"use client";

import {
  Alert,
  Badge,
  Button,
  Group,
  Modal,
  Stack,
  Table,
  Tabs,
  Text,
} from "@mantine/core";
import {
  CanAccess,
  useCan,
  useNotification,
  useTranslate,
} from "@refinedev/core";
import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { CreateListAction } from "@/components/access/CreateListAction";
import { ListTable } from "@/components/display/ListTable";
import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import { PageChrome } from "@/components/layout/PageChrome";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import {
  activateModelService,
  cleanupEmbeddingPurpose,
  closeEmbeddingPurpose,
  createModelService,
  deleteModelService,
  getEmbeddingPurpose,
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
  ModelService,
  ModelServiceFormValues,
  ModelServiceTestResult,
  PurposeState,
} from "@/features/model-services/types";
import { useConfirmAction } from "@/hooks/useConfirmAction";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { problemMessage } from "@/lib/problem";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;

function indexColor(status: PurposeState["index_status"]): string {
  if (status === "ready") return "green";
  if (status === "indexing") return "blue";
  if (status === "failed") return "red";
  return "gray";
}

export function ModelServiceList() {
  const t = useTranslate();
  const { open } = useNotification();
  const { data: canWrite } = useCan({
    resource: ModuleId.modelServices,
    action: ModuleAction.create,
  });

  const [purpose, setPurpose] = useState<PurposeState | null>(null);
  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<ModelService | undefined>();
  const [busy, setBusy] = useState(false);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResult, setTestResult] = useState<ModelServiceTestResult | null>(
    null,
  );
  const [opening, setOpening] = useState(false);
  const [closing, setClosing] = useState(false);
  const [cleaning, setCleaning] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [activatingId, setActivatingId] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState<string | null>("configure");
  const openConfirm = useConfirmAction<true>();
  const closeConfirm = useConfirmAction<true>();
  const cleanupConfirm = useConfirmAction<true>();
  const deleteConfirm = useConfirmAction<ModelService>();
  const activateConfirm = useConfirmAction<ModelService>();
  const { data: canListSchedules } = useCan({
    resource: ModuleId.schedules,
    action: ModuleAction.list,
  });

  const fetchPage = useCallback(
    (query: PageQuery) => listModelServices(query),
    [],
  );
  const list = useConsolePagedList({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
  });
  const { items, reload } = list;
  const showActions = Boolean(canWrite?.can);

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

  const refreshAll = async () => {
    await Promise.all([reload(), reloadPurpose()]);
  };

  const save = async (values: ModelServiceFormValues) => {
    setBusy(true);
    try {
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
    } catch (err) {
      notifyError(err, t("common.error.loadFailed"));
    } finally {
      setBusy(false);
    }
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
  const showScheduleLink = Boolean(
    canListSchedules?.can && purpose?.embed_schedule,
  );

  return (
    <PageChrome
      title={t("modelServices.title")}
      description={t("modelServices.description")}
    >
      <Tabs value={activeTab} onChange={setActiveTab}>
        <Tabs.List>
          <Tabs.Tab value="configure">
            {t("modelServices.tabs.configure")}
          </Tabs.Tab>
          <Tabs.Tab value="status">{t("modelServices.tabs.status")}</Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="configure" pt="md">
          <Stack gap="md">
            <Group justify="flex-end">{createAction}</Group>
            <ListTable
              list={list}
              columnCount={showActions ? 7 : 6}
              emptyMessage={t("modelServices.empty")}
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
                    <Text fw={600}>{row.display_name}</Text>
                  </Table.Td>
                  <Table.Td>{t(`modelServices.protocol.${row.protocol}`)}</Table.Td>
                  <Table.Td>
                    <Text size="sm" lineClamp={1}>
                      {row.url}
                    </Text>
                  </Table.Td>
                  <Table.Td>{row.model}</Table.Td>
                  <Table.Td>
                    <Badge color={row.in_use ? "green" : "gray"} variant="light">
                      {row.in_use
                        ? t("modelServices.status.inUse")
                        : t("modelServices.status.draft")}
                    </Badge>
                  </Table.Td>
                  <Table.Td>
                    {row.has_secret
                      ? t("modelServices.status.secretSet")
                      : t("modelServices.status.secretNone")}
                  </Table.Td>
                  {showActions ? (
                    <Table.Td>
                      <Group gap="xs" wrap="wrap">
                        <CanAccess
                          resource={ModuleId.modelServices}
                          action={ModuleAction.edit}
                        >
                          <Button
                            size="compact-xs"
                            variant="light"
                            onClick={() => {
                              setEditing(row);
                              setFormOpen(true);
                            }}
                          >
                            {t("actions.edit")}
                          </Button>
                        </CanAccess>
                        <CanAccess
                          resource={ModuleId.modelServices}
                          action={ModuleAction.edit}
                        >
                          <Button
                            size="compact-xs"
                            variant="light"
                            loading={testingId === row.id}
                            onClick={() => void runTest(row)}
                          >
                            {t("modelServices.test")}
                          </Button>
                        </CanAccess>
                        {!row.in_use ? (
                          <CanAccess
                            resource={ModuleId.modelServices}
                            action={ModuleAction.edit}
                          >
                            <Button
                              size="compact-xs"
                              variant="light"
                              loading={activatingId === row.id}
                              onClick={() => void openActivate(row)}
                            >
                              {t("modelServices.activate")}
                            </Button>
                          </CanAccess>
                        ) : null}
                        <CanAccess
                          resource={ModuleId.modelServices}
                          action={ModuleAction.delete}
                        >
                          <Button
                            size="compact-xs"
                            variant="light"
                            color="red"
                            onClick={() => deleteConfirm.open(row)}
                          >
                            {t("actions.delete")}
                          </Button>
                        </CanAccess>
                      </Group>
                    </Table.Td>
                  ) : null}
                </Table.Tr>
              ))}
            </ListTable>
          </Stack>
        </Tabs.Panel>
        <Tabs.Panel value="status" pt="md">
          <Stack gap="md">
            <Group justify="space-between" align="center">
              <Group gap="xs" align="center">
                <Text fw={600}>{t("modelServices.purpose.embedding")}</Text>
                <Badge
                  color={purpose?.closed ? "gray" : "green"}
                  variant="light"
                >
                  {purpose?.closed
                    ? t("modelServices.status.closed")
                    : t("modelServices.status.open")}
                </Badge>
                <Badge
                  color={indexColor(purpose?.index_status ?? "none")}
                  variant="light"
                >
                  {t(
                    `modelServices.index.${purpose?.index_status ?? "none"}`,
                  )}
                </Badge>
              </Group>
              {showActions || showScheduleLink ? (
                <Group gap="xs">
                  {showActions ? (
                    purpose?.closed ? (
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
                      component={Link}
                      href="/console/schedules"
                    >
                      {t("schedules.title")}
                    </Button>
                  ) : null}
                </Group>
              ) : null}
            </Group>
            {purpose?.closed ? (
              <Alert color="yellow" title={t("modelServices.closed.noteTitle")}>
                {t("modelServices.closed.note")}
              </Alert>
            ) : null}
          </Stack>
        </Tabs.Panel>
      </Tabs>

      <Modal.Stack>
        <Modal
          stackId="model-service-form"
          opened={formOpen}
          onClose={() => setFormOpen(false)}
          title={
            editing ? t("modelServices.edit") : t("modelServices.create")
          }
          size="lg"
        >
          <ModelServiceForm
            key={editing?.id ?? "create"}
            service={editing}
            loading={busy}
            onSubmit={(values) => void save(values)}
            onCancel={() => setFormOpen(false)}
          />
        </Modal>

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
  );
}
