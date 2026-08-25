"use client";

import {
  Badge,
  Button,
  Select,
  Stack,
  Text,
  Group,
  Modal,
  PasswordInput,
  SegmentedControl,
  Switch,
  Table,
  Tabs,
  TextInput,
} from "@mantine/core";
import {
  useCan,
  useGetIdentity,
  useList,
  useNotification,
  useTranslate,
  useUpdate,
} from "@refinedev/core";
import { useCallback, useState } from "react";

import { CreateListAction } from "@/components/access/CreateListAction";
import { ListTable } from "@/components/display/ListTable";
import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import { FillColumn } from "@/components/layout/FillColumn";
import { PageChrome } from "@/components/layout/PageChrome";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import { PendingFederatedIdentityTable } from "@/features/users/PendingFederatedIdentityTable";
import { UserRoleBadge } from "@/features/users/UserRoleBadge";
import { listUsers } from "@/features/users/api";
import type { RoleRow } from "@/features/roles/types";
import type { UserRow, UserStatus } from "@/features/users/types";
import { useConfirmAction } from "@/hooks/useConfirmAction";
import { useFormatInstant } from "@/hooks/useFormatInstant";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { ApiError } from "@/lib/api";
import {
  claimPendingFederatedIdentity,
  listPendingFederatedIdentities,
  unfederateUser,
} from "@/features/identity-providers/api";
import type { PendingFederatedIdentity } from "@/features/identity-providers/types";
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
  const { mutate: updateStatus, mutation } = useUpdate<UserRow>();
  const statusConfirm = useConfirmAction<UserRow>();
  const unfederateConfirm = useConfirmAction<UserRow>();
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
  const [activeTab, setActiveTab] = useState<string | null>("users");

  const fetchUsers = useCallback((query: PageQuery) => listUsers(query), []);
  const users = useConsolePagedList<UserRow>({
    pageSize: PAGE_SIZE,
    fetch: fetchUsers,
  });
  const { items: rows, reload } = users;

  const fetchPending = useCallback(
    (query: PageQuery) => listPendingFederatedIdentities(query),
    [],
  );
  const pendingList = useConsolePagedList({
    pageSize: PAGE_SIZE,
    fetch: fetchPending,
    enabled: Boolean(canWrite?.can),
  });

  const notifyError = (err: unknown, fallback: string) => {
    open?.({
      type: "error",
      message: err instanceof ApiError ? err.detail : fallback,
    });
  };

  const reloadPendingList = async () => {
    await pendingList.reload();
  };

  function confirmToggle() {
    const pending = statusConfirm.pending;
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
        onSuccess: () => {
          void reload();
        },
        onSettled: () => statusConfirm.close(),
      },
    );
  }

  const createAction = (
    <CreateListAction resource={ModuleId.users} href="/console/users/new">
      {t("users.create")}
    </CreateListAction>
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
        await reload();
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
      await reload();
    } catch (err) {
      notifyError(err, t("common.error.loadFailed"));
      setClaimBusy(false);
    }
  }

  async function confirmUnfederate() {
    if (!unfederateConfirm.pending || !unfederatePassword) return;
    setUnfederateBusy(true);
    try {
      await unfederateUser(unfederateConfirm.pending.id, unfederatePassword);
      unfederateConfirm.close();
      setUnfederatePassword("");
      await reload();
    } catch (err) {
      notifyError(err, t("common.error.loadFailed"));
    } finally {
      setUnfederateBusy(false);
    }
  }

  const userTable = (
    <ListTable
      list={users}
      columnCount={6}
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
                onChange={() => statusConfirm.open(row)}
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
                      unfederateConfirm.open(row);
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
  );

  const pendingBadge =
    pendingList.total > 0 ? (
      <Badge size="xs" variant="light">
        {pendingList.total}
      </Badge>
    ) : undefined;

  const content = canWrite?.can ? (
    <FillColumn>
      <Tabs
        value={activeTab}
        onChange={setActiveTab}
        keepMounted
        style={{
          flex: 1,
          minHeight: 0,
          display: "flex",
          flexDirection: "column",
        }}
        styles={{
          panel: {
            flex: 1,
            minHeight: 0,
            overflow: "auto",
            display: "flex",
            flexDirection: "column",
          },
        }}
      >
        <Tabs.List>
          <Tabs.Tab value="users">{t("users.tabs.users")}</Tabs.Tab>
          <Tabs.Tab value="pending" rightSection={pendingBadge}>
            {t("users.pending.title")}
          </Tabs.Tab>
        </Tabs.List>
        <Tabs.Panel value="users" pt="md" style={{ overflow: "hidden" }}>
          {userTable}
        </Tabs.Panel>
        <Tabs.Panel value="pending" pt="md" style={{ overflow: "hidden" }}>
          <PendingFederatedIdentityTable
            list={pendingList}
            onClaim={openClaim}
          />
        </Tabs.Panel>
      </Tabs>
    </FillColumn>
  ) : (
    userTable
  );

  return (
    <PageChrome
      title={t("users.title")}
      description={t("users.description")}
      actions={createAction}
    >
      {content}

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

      <ConfirmActionModal
        opened={unfederateConfirm.opened}
        onClose={() => {
          unfederateConfirm.close();
          setUnfederatePassword("");
        }}
        title={t("users.federation.unfederate.title")}
        confirmLabel={t("users.federation.unfederate.confirm")}
        loading={unfederateBusy}
        confirmDisabled={!unfederatePassword}
        onConfirm={() => void confirmUnfederate()}
      >
        <PasswordInput
          value={unfederatePassword}
          onChange={(event) =>
            setUnfederatePassword(event.currentTarget.value)
          }
          label={t("users.federation.unfederate.password")}
          required
        />
      </ConfirmActionModal>

      <ConfirmActionModal
        opened={statusConfirm.opened}
        onClose={statusConfirm.close}
        title={t("users.status.confirmTitle")}
        loading={mutation.isPending}
        onConfirm={confirmToggle}
      />
    </PageChrome>
  );
}
