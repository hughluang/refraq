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

import { ListTable } from "@/components/display/ListTable";
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
import { usePagedList } from "@/hooks/usePagedList";
import { ApiError } from "@/lib/api";
import { listPresentationOf } from "@/lib/list-state";
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
  const [pendingDelete, setPendingDelete] = useState<IdentityProvider | null>(
    null,
  );
  const [pendingDisable, setPendingDisable] = useState<IdentityProvider | null>(
    null,
  );
  const [disableBoundUsers, setDisableBoundUsers] = useState(false);
  const [cascadeOnDisable, setCascadeOnDisable] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [disabling, setDisabling] = useState(false);

  const onError = useCallback(
    (message: string) => {
      open?.({ type: "error", message });
    },
    [open],
  );
  const fetchPage = useCallback(
    (query: PageQuery) => listIdentityProviders(query),
    [],
  );
  const { items, total, page, setPage, loading, error, reload, pageSize } =
    usePagedList({
      pageSize: PAGE_SIZE,
      fetch: fetchPage,
      onError,
    });
  const listPresentation = listPresentationOf({
    loading,
    error,
    total,
    itemCount: items.length,
    filtered: false,
  });
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
      setPendingDisable(row);
      setCascadeOnDisable(false);
      try {
        const { provider } = await getIdentityProvider(row.id);
        setPendingDisable(provider);
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
    if (!pendingDisable) return;
    setDisabling(true);
    try {
      await patchIdentityProvider(
        pendingDisable.id,
        { enabled: false },
        { disableBoundUsers: cascadeOnDisable },
      );
      open?.({
        type: "success",
        message: t("identityProviders.disable.success"),
      });
      setPendingDisable(null);
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
    setPendingDelete(row);
    setDisableBoundUsers(false);
    try {
      const { provider } = await getIdentityProvider(row.id);
      setPendingDelete(provider);
    } catch (err) {
      notifyError(err, t("common.error.loadFailed"));
    }
  };

  const confirmDelete = async () => {
    if (!pendingDelete) return;
    setDeleting(true);
    try {
      await deleteIdentityProvider(pendingDelete.id, disableBoundUsers);
      open?.({
        type: "success",
        message: t("identityProviders.delete.success"),
      });
      setPendingDelete(null);
      await reload();
    } catch (err) {
      notifyError(err, t("common.error.loadFailed"));
    } finally {
      setDeleting(false);
    }
  };

  const createAction = (
    <CanAccess
      resource={ModuleId.identityProviders}
      action={ModuleAction.create}
    >
      <Button
        size="sm"
        onClick={() => {
          setEditing(undefined);
          setFormOpen(true);
        }}
      >
        {t("identityProviders.create")}
      </Button>
    </CanAccess>
  );

  return (
    <PageChrome
      title={t("identityProviders.title")}
      description={t("identityProviders.description")}
      actions={createAction}
    >
      <ListTable
        state={listPresentation.state}
        columnCount={showActions ? 8 : 7}
        refreshing={listPresentation.refreshing}
        errorMessage={error}
        onRetry={() => void reload()}
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
        page={page}
        pageSize={pageSize}
        total={total}
        onPageChange={setPage}
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

        <Modal
          stackId="identity-provider-disable"
          opened={pendingDisable !== null}
          onClose={() => setPendingDisable(null)}
          title={t("identityProviders.disable.confirmTitle")}
          size="md"
        >
          <Stack gap="md">
            <Text size="sm">
              {pendingDisable
                ? t("identityProviders.disable.confirmBody", {
                    count: pendingDisable.bound_user_count,
                  })
                : null}
            </Text>
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
            <Group justify="flex-end">
              <Button
                variant="default"
                onClick={() => setPendingDisable(null)}
                disabled={disabling}
              >
                {t("common.cancel")}
              </Button>
              <Button
                color="red"
                loading={disabling}
                onClick={() => void confirmDisable()}
              >
                {t("common.confirm")}
              </Button>
            </Group>
          </Stack>
        </Modal>

        <Modal
          stackId="identity-provider-delete"
          opened={pendingDelete !== null}
          onClose={() => setPendingDelete(null)}
          title={t("identityProviders.delete.confirmTitle")}
          size="md"
        >
          <Stack gap="md">
            <Text size="sm">
              {pendingDelete
                ? t("identityProviders.delete.confirmBody", {
                    count: pendingDelete.bound_user_count,
                  })
                : null}
            </Text>
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
    </PageChrome>
  );
}
