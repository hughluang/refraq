"use client";

import {
  Badge,
  Button,
  Checkbox,
  Code,
  Group,
  Modal,
  Stack,
  Table,
  Text,
} from "@mantine/core";
import {
  CanAccess,
  useCan,
  useNotification,
  useTranslate,
} from "@refinedev/core";
import { useCallback, useState } from "react";

import { CreateListAction } from "@/components/access/CreateListAction";
import { ListTable } from "@/components/display/ListTable";
import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import { PageChrome } from "@/components/layout/PageChrome";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import {
  createIdentityProvider,
  deleteIdentityProvider,
  getIdentityProvider,
  listIdentityProviders,
  patchIdentityProvider,
  testIdentityProvider,
} from "@/features/identity-providers/api";
import {
  SpecDrivenForm,
  providerPayload,
} from "@/features/identity-providers/SpecDrivenForm";
import type {
  IdentityProvider,
  IdentityProviderFormValues,
  IdentityProviderTestResult,
} from "@/features/identity-providers/types";
import { useConfirmAction } from "@/hooks/useConfirmAction";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { ApiError } from "@/lib/api";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;

export function IdentityProviderList() {
  const t = useTranslate();
  const { open } = useNotification();
  const { data: canWrite } = useCan({
    resource: ModuleId.identityProviders,
    action: ModuleAction.create,
  });

  const [formOpen, setFormOpen] = useState(false);
  const [editing, setEditing] = useState<IdentityProvider | undefined>();
  const [busy, setBusy] = useState(false);
  const [testingId, setTestingId] = useState<string | null>(null);
  const [testResult, setTestResult] =
    useState<IdentityProviderTestResult | null>(null);
  const deleteConfirm = useConfirmAction<IdentityProvider>();
  const disableConfirm = useConfirmAction<IdentityProvider>();
  const [disableBoundUsers, setDisableBoundUsers] = useState(false);
  const [cascadeOnDisable, setCascadeOnDisable] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [disabling, setDisabling] = useState(false);

  const fetchPage = useCallback(
    (query: PageQuery) => listIdentityProviders(query),
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
      message: err instanceof ApiError ? err.detail : fallback,
    });
  };

  const save = async (values: IdentityProviderFormValues) => {
    setBusy(true);
    try {
      const payload = providerPayload(values, editing ? "edit" : "create");
      if (editing) {
        await patchIdentityProvider(editing.id, payload);
        open?.({
          type: "success",
          message: t("identityProviders.update.success"),
        });
      } else {
        await createIdentityProvider(payload);
        open?.({
          type: "success",
          message: t("identityProviders.create.success"),
        });
      }
      setFormOpen(false);
      setEditing(undefined);
      await reload();
    } catch (err) {
      notifyError(err, t("common.error.loadFailed"));
    } finally {
      setBusy(false);
    }
  };

  const toggleEnabled = async (row: IdentityProvider) => {
    if (row.enabled) {
      disableConfirm.open(row);
      setCascadeOnDisable(false);
      try {
        const { provider } = await getIdentityProvider(row.id);
        disableConfirm.open(provider);
      } catch (err) {
        notifyError(err, t("common.error.loadFailed"));
      }
      return;
    }
    try {
      await patchIdentityProvider(row.id, { enabled: true });
      open?.({
        type: "success",
        message: t("identityProviders.enable.success"),
      });
      await reload();
    } catch (err) {
      notifyError(err, t("common.error.loadFailed"));
    }
  };

  const confirmDisable = async () => {
    const pending = disableConfirm.pending;
    if (!pending) return;
    setDisabling(true);
    try {
      await patchIdentityProvider(
        pending.id,
        { enabled: false },
        { disableBoundUsers: cascadeOnDisable },
      );
      open?.({
        type: "success",
        message: t("identityProviders.disable.success"),
      });
      disableConfirm.close();
      await reload();
    } catch (err) {
      notifyError(err, t("common.error.loadFailed"));
    } finally {
      setDisabling(false);
    }
  };

  const runTest = async (row: IdentityProvider) => {
    setTestingId(row.id);
    try {
      const result = await testIdentityProvider(row.id);
      setTestResult(result);
    } catch (err) {
      notifyError(err, t("identityProviders.test.failed"));
    } finally {
      setTestingId(null);
    }
  };

  const openDelete = async (row: IdentityProvider) => {
    deleteConfirm.open(row);
    setDisableBoundUsers(false);
    try {
      const { provider } = await getIdentityProvider(row.id);
      deleteConfirm.open(provider);
    } catch (err) {
      notifyError(err, t("common.error.loadFailed"));
    }
  };

  const confirmDelete = async () => {
    const pending = deleteConfirm.pending;
    if (!pending) return;
    setDeleting(true);
    try {
      await deleteIdentityProvider(pending.id, disableBoundUsers);
      open?.({
        type: "success",
        message: t("identityProviders.delete.success"),
      });
      deleteConfirm.close();
      await reload();
    } catch (err) {
      notifyError(err, t("common.error.loadFailed"));
    } finally {
      setDeleting(false);
    }
  };

  const createAction = (
    <CreateListAction
      resource={ModuleId.identityProviders}
      onClick={() => {
        setEditing(undefined);
        setFormOpen(true);
      }}
    >
      {t("identityProviders.create")}
    </CreateListAction>
  );

  return (
    <PageChrome
      title={t("identityProviders.title")}
      description={t("identityProviders.description")}
      actions={createAction}
    >
      <ListTable
        list={list}
        columnCount={showActions ? 8 : 7}
        emptyMessage={t("identityProviders.empty")}
        head={
          <Table.Tr>
            <Table.Th>{t("identityProviders.fields.display_name")}</Table.Th>
            <Table.Th>{t("identityProviders.fields.protocol")}</Table.Th>
            <Table.Th>{t("identityProviders.fields.issuer")}</Table.Th>
            <Table.Th>{t("identityProviders.fields.group_claim")}</Table.Th>
            <Table.Th>{t("identityProviders.fields.status")}</Table.Th>
            <Table.Th>
              {t("identityProviders.fields.client_secret_configured")}
            </Table.Th>
            <Table.Th>{t("identityProviders.fields.boundUsers")}</Table.Th>
            {showActions ? (
              <Table.Th>{t("identityProviders.fields.actions")}</Table.Th>
            ) : null}
          </Table.Tr>
        }
      >
        {items.map((row) => (
          <Table.Tr key={row.id}>
            <Table.Td>
              <Text fw={600}>{row.display_name}</Text>
            </Table.Td>
            <Table.Td>{row.protocol}</Table.Td>
            <Table.Td>
              <Text size="sm" lineClamp={1}>
                {row.issuer}
              </Text>
            </Table.Td>
            <Table.Td>
              {row.group_claim || t("identityProviders.fields.notConfigured")}
            </Table.Td>
            <Table.Td>
              <Badge color={row.enabled ? "green" : "gray"} variant="light">
                {row.enabled
                  ? t("identityProviders.status.enabled")
                  : t("identityProviders.status.disabled")}
              </Badge>
            </Table.Td>
            <Table.Td>
              {row.client_secret_configured
                ? t("identityProviders.status.enabled")
                : t("identityProviders.fields.notConfigured")}
            </Table.Td>
            <Table.Td>{row.bound_user_count}</Table.Td>
            {showActions ? (
              <Table.Td>
                <Group gap="xs" wrap="wrap">
                  <CanAccess
                    resource={ModuleId.identityProviders}
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
                    resource={ModuleId.identityProviders}
                    action={ModuleAction.edit}
                  >
                    <Button
                      size="compact-xs"
                      variant="light"
                      onClick={() => void toggleEnabled(row)}
                    >
                      {row.enabled
                        ? t("identityProviders.disable")
                        : t("identityProviders.enable")}
                    </Button>
                  </CanAccess>
                  <CanAccess
                    resource={ModuleId.identityProviders}
                    action={ModuleAction.edit}
                  >
                    <Button
                      size="compact-xs"
                      variant="light"
                      loading={testingId === row.id}
                      onClick={() => void runTest(row)}
                    >
                      {t("identityProviders.test")}
                    </Button>
                  </CanAccess>
                  <CanAccess
                    resource={ModuleId.identityProviders}
                    action={ModuleAction.delete}
                  >
                    <Button
                      size="compact-xs"
                      variant="light"
                      color="red"
                      onClick={() => void openDelete(row)}
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

      <Modal.Stack>
        <Modal
          stackId="identity-provider-form"
          opened={formOpen}
          onClose={() => setFormOpen(false)}
          title={
            editing
              ? t("identityProviders.edit")
              : t("identityProviders.create")
          }
          size="lg"
        >
          <SpecDrivenForm
            key={editing?.id ?? "create"}
            provider={editing}
            loading={busy}
            onSubmit={(values) => void save(values)}
            onCancel={() => setFormOpen(false)}
          />
        </Modal>

        <Modal
          stackId="identity-provider-test"
          opened={testResult !== null}
          onClose={() => setTestResult(null)}
          title={t("identityProviders.test")}
          size="md"
        >
          {testResult ? (
            <Stack gap="sm">
              <Text size="sm">
                {t("identityProviders.test.issuer")}: {testResult.issuer}
              </Text>
              <Text size="sm">
                {t("identityProviders.test.groupClaim")}:{" "}
                <Code>{testResult.group_claim}</Code>
              </Text>
              <Text size="sm" c="dimmed">
                {t("identityProviders.test.scopeHint")}
              </Text>
              <Text size="sm" c="dimmed">
                {t("identityProviders.test.noGroupsHint")}
              </Text>
            </Stack>
          ) : null}
        </Modal>

        <ConfirmActionModal
          stackId="identity-provider-disable"
          opened={disableConfirm.opened}
          onClose={disableConfirm.close}
          title={t("identityProviders.disable.confirmTitle")}
          body={
            disableConfirm.pending
              ? t("identityProviders.disable.confirmBody", {
                  count: disableConfirm.pending.bound_user_count,
                })
              : null
          }
          confirmColor="red"
          loading={disabling}
          size="md"
          onConfirm={() => void confirmDisable()}
        >
          <Checkbox
            label={t("identityProviders.disable.disableBound")}
            checked={cascadeOnDisable}
            onChange={(event) =>
              setCascadeOnDisable(event.currentTarget.checked)
            }
          />
          {cascadeOnDisable ? (
            <Text size="sm" c="dimmed">
              {t("identityProviders.disable.skipSelf")}
            </Text>
          ) : null}
        </ConfirmActionModal>

        <ConfirmActionModal
          stackId="identity-provider-delete"
          opened={deleteConfirm.opened}
          onClose={deleteConfirm.close}
          title={t("identityProviders.delete.confirmTitle")}
          body={
            deleteConfirm.pending
              ? t("identityProviders.delete.confirmBody", {
                  count: deleteConfirm.pending.bound_user_count,
                })
              : null
          }
          confirmColor="red"
          loading={deleting}
          size="md"
          onConfirm={() => void confirmDelete()}
        >
          <Checkbox
            label={t("identityProviders.delete.disableBound")}
            checked={disableBoundUsers}
            onChange={(event) =>
              setDisableBoundUsers(event.currentTarget.checked)
            }
          />
          {disableBoundUsers ? (
            <Text size="sm" c="dimmed">
              {t("identityProviders.disable.skipSelf")}
            </Text>
          ) : null}
        </ConfirmActionModal>
      </Modal.Stack>
    </PageChrome>
  );
}
