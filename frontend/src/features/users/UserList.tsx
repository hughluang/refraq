"use client";

import {
  Button,
  Paper,
  Select,
  Stack,
  Text,
  Group,
  Modal,
  PasswordInput,
  SegmentedControl,
  Switch,
  Table,
  TextInput,
} from "@mantine/core";
import {
  CanAccess,
  useCan,
  useGetIdentity,
  useList,
  useNotification,
  useTable,
  useTranslate,
  useUpdate,
} from "@refinedev/core";
import Link from "next/link";
import { useCallback, useState } from "react";

import { ListPager } from "@/components/display/ListPager";
import { ListTable } from "@/components/display/ListTable";
import { PageError } from "@/components/feedback/PageError";
import { PageChrome } from "@/components/layout/PageChrome";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import { UserRoleBadge } from "@/features/users/UserRoleBadge";
import type { RoleRow } from "@/features/roles/types";
import type { UserRow, UserStatus } from "@/features/users/types";
import { useFormatInstant } from "@/hooks/useFormatInstant";
import { usePagedList } from "@/hooks/usePagedList";
import { ApiError } from "@/lib/api";
import {
  claimPendingFederatedIdentity,
  listPendingFederatedIdentities,
  unfederateUser,
} from "@/features/identity-providers/api";
import type { PendingFederatedIdentity } from "@/features/identity-providers/types";
import { listPresentationOf } from "@/lib/list-state";
import type { PageQuery } from "@/lib/pagination";
import type { CurrentUser } from "@/providers/session-store";

const PAGE_SIZE = 50;

export function UserList() {
  const t = useTranslate();
  const { open } = useNotification();
  const formatInstant = useFormatInstant();
  const { data: identity } = useGetIdentity<CurrentUser>();
  const { data: canWrite } = useCan({
    resource: ModuleId.users,
    action: ModuleAction.create,
  });
  const rolesQuery = useList<RoleRow>({
    resource: ModuleId.roles,
    pagination: { mode: "off" },
  });
  const claimUsersQuery = useList<UserRow>({
    resource: ModuleId.users,
    pagination: { mode: "off" },
    queryOptions: { enabled: Boolean(canWrite?.can) },
  });
  const { tableQuery, currentPage, setCurrentPage } = useTable<UserRow>({
    resource: ModuleId.users,
    pagination: { mode: "server", pageSize: PAGE_SIZE },
  });
  const { mutate: updateStatus, mutation } = useUpdate<UserRow>();
  const [pending, setPending] = useState<UserRow | null>(null);
  const [unfederateTarget, setUnfederateTarget] = useState<UserRow | null>(
    null,
  );
  const [unfederatePassword, setUnfederatePassword] = useState("");
  const [unfederateBusy, setUnfederateBusy] = useState(false);
  const [claimTarget, setClaimTarget] = useState<PendingFederatedIdentity | null>(
    null,
  );
  const [claimMode, setClaimMode] = useState<"existing" | "create">("create");
  const [claimAccount, setClaimAccount] = useState("");
  const [claimDisplayName, setClaimDisplayName] = useState("");
  const [claimUserId, setClaimUserId] = useState<string | null>(null);
  const [claimRoleId, setClaimRoleId] = useState<string | null>(null);
  const [claimBusy, setClaimBusy] = useState(false);

  const fetchPending = useCallback(
    (query: PageQuery) => listPendingFederatedIdentities(query),
    [],
  );
  const {
    items: pendingIdentities,
    total: pendingTotal,
    page: pendingPage,
    setPage: setPendingPage,
    loading: pendingLoading,
    error: pendingError,
    errorRequestId: pendingRequestId,
    reload: reloadPending,
    pageSize: pendingPageSize,
  } = usePagedList({
    pageSize: PAGE_SIZE,
    fetch: fetchPending,
    enabled: Boolean(canWrite?.can),
  });

  const rows = tableQuery.data?.data ?? [];
  const total = tableQuery.data?.total ?? 0;
  const errorMessage =
    tableQuery.error == null
      ? null
      : tableQuery.error instanceof ApiError
        ? tableQuery.error.detail
        : t("common.error.loadFailed");
  const listPresentation = listPresentationOf({
    loading: tableQuery.isFetching,
    error: errorMessage,
    total,
    itemCount: rows.length,
    filtered: false,
  });

  const notifyError = (err: unknown, fallback: string) => {
    open?.({
      type: "error",
      message: err instanceof ApiError ? err.detail : fallback,
    });
  };

  const reloadPendingList = async () => {
    await reloadPending();
  };

  function confirmToggle() {
    if (!pending) return;
    const next: UserStatus =
      pending.status === "active" ? "disabled" : "active";
    updateStatus(
      {
        resource: ModuleId.users,
        id: pending.id,
        values: { status: next },
        meta: { action: "status" },
        successNotification: {
          message: t("users.title"),
          description: t("users.status.update.success"),
          type: "success",
        },
        errorNotification: (err) => ({
          message: t("users.title"),
          description:
            err instanceof ApiError
              ? err.detail
              : t("users.status.update.error"),
          type: "error",
        }),
      },
      {
        onSettled: () => setPending(null),
      },
    );
  }

  const createAction = (
    <CanAccess resource={ModuleId.users} action={ModuleAction.create}>
      <Button component={Link} href="/console/users/new" size="sm">
        {t("users.create")}
      </Button>
    </CanAccess>
  );

  const roleOptions = (rolesQuery.result?.data ?? []).map((role) => ({
    value: role.id,
    label: role.name,
  }));
  const claimableUsers = (claimUsersQuery.result?.data ?? [])
    .filter((row) => row.identity_source === "local")
    .map((row) => ({ value: row.id, label: row.account }));

  const openClaim = (item: PendingFederatedIdentity) => {
    setClaimTarget(item);
    setClaimMode("create");
    setClaimAccount(item.account_hint);
    setClaimDisplayName(item.display_name ?? item.account_hint);
    setClaimUserId(null);
    setClaimRoleId(null);
  };

  const closeClaim = () => {
    setClaimTarget(null);
    setClaimBusy(false);
  };

  async function submitClaim() {
    if (!claimTarget) return;
    if (claimMode === "existing") {
      if (!claimUserId) return;
      setClaimBusy(true);
      try {
        await claimPendingFederatedIdentity(claimTarget.id, {
          user_id: claimUserId,
        });
        closeClaim();
        await reloadPendingList();
        await tableQuery.refetch();
      } catch (err) {
        notifyError(err, t("common.error.loadFailed"));
        setClaimBusy(false);
      }
      return;
    }
    if (!claimRoleId || !claimAccount.trim() || !claimDisplayName.trim()) return;
    setClaimBusy(true);
    try {
      await claimPendingFederatedIdentity(claimTarget.id, {
        create_user: {
          account: claimAccount.trim(),
          display_name: claimDisplayName.trim(),
          email: claimTarget.email,
          role_id: claimRoleId,
        },
      });
      closeClaim();
      await reloadPendingList();
      await tableQuery.refetch();
    } catch (err) {
      notifyError(err, t("common.error.loadFailed"));
      setClaimBusy(false);
    }
  }

  async function confirmUnfederate() {
    if (!unfederateTarget || !unfederatePassword) return;
    setUnfederateBusy(true);
    try {
      await unfederateUser(unfederateTarget.id, unfederatePassword);
      setUnfederateTarget(null);
      setUnfederatePassword("");
      await tableQuery.refetch();
    } catch (err) {
      notifyError(err, t("common.error.loadFailed"));
    } finally {
      setUnfederateBusy(false);
    }
  }

  return (
    <PageChrome
      title={t("users.title")}
      description={t("users.description")}
      actions={createAction}
    >
      {canWrite?.can ? (
        <Stack gap="xs" mb="md">
          <Text fw={600}>{t("users.pending.title")}</Text>
          {pendingError ? (
            <PageError
              message={pendingError}
              requestId={pendingRequestId}
              onRetry={() => void reloadPending()}
            />
          ) : pendingLoading && pendingIdentities.length === 0 ? (
            <Text size="sm" c="dimmed">
              {t("common.loading")}
            </Text>
          ) : pendingIdentities.length === 0 ? (
            <Text size="sm" c="dimmed">
              {t("users.pending.empty")}
            </Text>
          ) : (
            <>
              {pendingIdentities.map((item) => (
              <Paper key={item.id} withBorder p="sm">
                <Group justify="space-between" align="flex-start" wrap="wrap">
                  <Stack gap={4}>
                    <Text fw={500}>
                      {item.display_name ?? item.account_hint}
                    </Text>
                    <Text size="xs" c="dimmed">
                      {item.account_hint}
                      {item.email ? ` · ${item.email}` : ""}
                      {` · ${item.issuer}`}
                    </Text>
                    <Text size="xs">
                      {t("users.pending.reason")}:{" "}
                      {t(`users.pending.reason.${item.admission_reason}`, {
                        defaultValue: item.admission_reason,
                      })}
                    </Text>
                    <Text size="xs">
                      {t("users.pending.groups")}:{" "}
                      {item.groups.length
                        ? item.groups.join(", ")
                        : t("identityProviders.fields.notConfigured")}
                    </Text>
                    <Text size="xs">
                      {t("users.pending.expires")}:{" "}
                      {formatInstant(item.expires_at)}
                    </Text>
                    <Text size="xs">
                      {t("users.pending.attempts")}: {item.attempt_count}
                    </Text>
                  </Stack>
                  <Button
                    size="xs"
                    onClick={() => openClaim(item)}
                  >
                    {t("users.pending.claim")}
                  </Button>
                </Group>
              </Paper>
              ))}
              <ListPager
                page={pendingPage}
                pageSize={pendingPageSize}
                total={pendingTotal}
                onChange={setPendingPage}
                disabled={pendingLoading}
              />
            </>
          )}
        </Stack>
      ) : null}

      <ListTable
        state={listPresentation.state}
        columnCount={6}
        refreshing={listPresentation.refreshing}
        errorMessage={errorMessage}
        onRetry={() => void tableQuery.refetch()}
        head={
          <Table.Tr>
            <Table.Th>{t("users.fields.account")}</Table.Th>
            <Table.Th>{t("users.fields.displayName")}</Table.Th>
            <Table.Th>{t("users.fields.role")}</Table.Th>
            <Table.Th>{t("users.fields.status")}</Table.Th>
            <Table.Th>{t("users.fields.identity")}</Table.Th>
            <Table.Th>{t("users.fields.lastLoginAt")}</Table.Th>
          </Table.Tr>
        }
        page={currentPage}
        pageSize={PAGE_SIZE}
        total={total}
        onPageChange={setCurrentPage}
      >
        {rows.map((row) => {
          const isSelf = identity?.id === row.id;
          return (
            <Table.Tr key={row.id}>
              <Table.Td>{row.account}</Table.Td>
              <Table.Td>{row.display_name}</Table.Td>
              <Table.Td>
                <UserRoleBadge
                  roleName={row.role_name}
                  roleKey={row.role_key}
                />
              </Table.Td>
              <Table.Td>
                <Switch
                  checked={row.status === "active"}
                  onChange={() => setPending(row)}
                  disabled={!canWrite?.can || mutation.isPending || isSelf}
                  size="sm"
                  aria-label={
                    row.status === "active"
                      ? t("users.status.active")
                      : t("users.status.disabled")
                  }
                />
              </Table.Td>
              <Table.Td>
                <Group gap="xs">
                  <Text size="sm">
                    {t(`identitySource.${row.identity_source}`)}
                  </Text>
                  {row.identity_source === "oidc" && canWrite?.can ? (
                    <Button
                      size="compact-xs"
                      variant="subtle"
                      onClick={() => {
                        setUnfederateTarget(row);
                        setUnfederatePassword("");
                      }}
                    >
                      {t("users.federation.unfederate.title")}
                    </Button>
                  ) : null}
                </Group>
              </Table.Td>
              <Table.Td>{formatInstant(row.last_login_at)}</Table.Td>
            </Table.Tr>
          );
        })}
      </ListTable>

      <Modal
        opened={claimTarget !== null}
        onClose={closeClaim}
        title={t("users.pending.claimTitle")}
        centered
      >
        <Stack gap="sm">
          <SegmentedControl
            fullWidth
            value={claimMode}
            onChange={(value) =>
              setClaimMode(value === "existing" ? "existing" : "create")
            }
            data={[
              {
                value: "create",
                label: t("users.pending.createUser"),
              },
              {
                value: "existing",
                label: t("users.pending.claimExisting"),
              },
            ]}
          />
          {claimMode === "existing" ? (
            <Select
              label={t("users.pending.claimExisting")}
              data={claimableUsers}
              clearable
              value={claimUserId}
              onChange={setClaimUserId}
            />
          ) : (
            <>
              <TextInput
                label={t("users.fields.account")}
                value={claimAccount}
                onChange={(event) => setClaimAccount(event.currentTarget.value)}
                required
              />
              <TextInput
                label={t("users.fields.displayName")}
                value={claimDisplayName}
                onChange={(event) =>
                  setClaimDisplayName(event.currentTarget.value)
                }
                required
              />
              <Select
                label={t("users.fields.role")}
                data={roleOptions}
                required
                value={claimRoleId}
                onChange={setClaimRoleId}
              />
            </>
          )}
          <Group justify="flex-end">
            <Button variant="default" onClick={closeClaim} disabled={claimBusy}>
              {t("common.cancel")}
            </Button>
            <Button
              loading={claimBusy}
              disabled={
                claimMode === "existing"
                  ? !claimUserId
                  : !claimRoleId ||
                    !claimAccount.trim() ||
                    !claimDisplayName.trim()
              }
              onClick={() => void submitClaim()}
            >
              {t("users.pending.claim")}
            </Button>
          </Group>
        </Stack>
      </Modal>

      <Modal
        opened={unfederateTarget !== null}
        onClose={() => setUnfederateTarget(null)}
        title={t("users.federation.unfederate.title")}
        centered
      >
        <PasswordInput
          value={unfederatePassword}
          onChange={(event) =>
            setUnfederatePassword(event.currentTarget.value)
          }
          label={t("users.federation.unfederate.password")}
          required
        />
        <Group justify="flex-end" mt="md">
          <Button
            onClick={() => setUnfederateTarget(null)}
            variant="default"
            disabled={unfederateBusy}
          >
            {t("common.cancel")}
          </Button>
          <Button
            loading={unfederateBusy}
            disabled={!unfederatePassword}
            onClick={() => void confirmUnfederate()}
          >
            {t("users.federation.unfederate.confirm")}
          </Button>
        </Group>
      </Modal>

      <Modal
        opened={pending !== null}
        onClose={() => setPending(null)}
        title={t("users.status.confirmTitle")}
        centered
      >
        <Group justify="flex-end" mt="md">
          <Button variant="default" onClick={() => setPending(null)}>
            {t("common.cancel")}
          </Button>
          <Button loading={mutation.isPending} onClick={confirmToggle}>
            {t("common.confirm")}
          </Button>
        </Group>
      </Modal>
    </PageChrome>
  );
}
