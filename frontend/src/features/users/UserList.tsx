"use client";

import { Badge, Stack, Text, Group, PasswordInput, Table } from "@mantine/core";
import {
  useCan,
  useGetIdentity,
  useNotification,
  useTranslate,
  useUpdate,
} from "@refinedev/core";
import { useCallback, useMemo, useState, type ReactNode } from "react";

import { CreateListAction } from "@/components/access/CreateListAction";
import { FormDialog } from "@/components/form/FormDialog";
import {
  FormErrorSummary,
  saveFailureFrom,
  type SaveFailure,
} from "@/components/form/FormErrorSummary";
import { RecordPicker } from "@/components/form/RecordPicker";
import {
  roleRecordAdapter,
  userRecordAdapter,
} from "@/components/form/recordPickerAdapters";
import { SegmentedField } from "@/components/form/SegmentedField";
import { useConsoleForm } from "@/components/form/useConsoleForm";
import { TextField } from "@/components/form/TextField";
import { ListTable } from "@/components/display/ListTable";
import { ListToolbar } from "@/components/display/ListToolbar";
import { RecordReference } from "@/components/display/RecordReference";
import { RowActions } from "@/components/display/RowActions";
import { PageTabs, useConsoleTab } from "@/components/layout/consoleTabs";
import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import { useConsoleMutation } from "@/components/feedback/useConsoleMutation";
import { FillColumn } from "@/components/layout/FillColumn";
import { PageChrome } from "@/components/layout/PageChrome";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import { PendingFederatedIdentityTable } from "@/features/users/PendingFederatedIdentityTable";
import { UserRoleBadge } from "@/features/users/UserRoleBadge";
import { listUsers } from "@/features/users/api";
import type { UserRow, UserStatus } from "@/features/users/types";
import { useConfirmAction } from "@/hooks/useConfirmAction";
import { useShowInstant } from "@/hooks/useFormatInstant";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { useListQuery } from "@/hooks/useListQuery";
import { problemMessage } from "@/lib/problem";
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
  const showInstant = useShowInstant();
  const { data: identity } = useGetIdentity<CurrentUser>();
  const { data: canWrite } = useCan({
    resource: ModuleId.users,
    action: ModuleAction.create,
  });
  const { mutate: updateStatus } = useUpdate<UserRow>();
  const statusAction = useConsoleMutation();
  const unfederateConfirm = useConfirmAction<UserRow>();
  const [unfederatePassword, setUnfederatePassword] = useState("");
  const [unfederateBusy, setUnfederateBusy] = useState(false);
  const [claimTarget, setClaimTarget] = useState<PendingFederatedIdentity | null>(
    null,
  );
  const [claimFailure, setClaimFailure] = useState<SaveFailure | null>(null);
  const claimForm = useConsoleForm<{
    mode: "create" | "existing";
    account: string;
    display_name: string;
    role_id: string | null;
    user_id: string | null;
  }>({
    initialValues: {
      mode: "create",
      account: "",
      display_name: "",
      role_id: null,
      user_id: null,
    },
    onValuesChange: () => setClaimFailure(null),
    validate: {
      account: (value, values) =>
        values.mode === "create" && !value.trim()
          ? t("users.validation.required")
          : null,
      display_name: (value, values) =>
        values.mode === "create" && !value.trim()
          ? t("users.validation.required")
          : null,
      role_id: (value, values) =>
        values.mode === "create" && !value ? t("users.validation.required") : null,
      user_id: (value, values) =>
        values.mode === "existing" && !value
          ? t("users.validation.required")
          : null,
    },
  });
  const userTabs = useMemo(
    () =>
      canWrite?.can
        ? [{ value: "users" }, { value: "pending" }]
        : [{ value: "users" }],
    [canWrite?.can],
  );
  const { value: activeTab, setTab } = useConsoleTab(userTabs);
  const usersQuery = useListQuery();
  const pendingQuery = useListQuery({ search: false, pageKey: "pending" });

  const fetchUsers = useCallback(
    (page: PageQuery) =>
      listUsers({ ...page, q: usersQuery.search || undefined }),
    [usersQuery.search],
  );
  const users = useConsolePagedList<UserRow>({
    pageSize: PAGE_SIZE,
    fetch: fetchUsers,
    resetDeps: [usersQuery.search],
    filtered: usersQuery.isFiltered,
    page: usersQuery.page,
    onPageChange: usersQuery.setPage,
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
    page: pendingQuery.page,
    onPageChange: pendingQuery.setPage,
  });

  const notifyError = (err: unknown, fallback: string) => {
    open?.({
      type: "error",
      message: problemMessage(t, err, fallback),
    });
  };

  const reloadPendingList = async () => {
    await pendingList.reload();
  };

  function setUserStatus(row: UserRow, status: UserStatus) {
    return new Promise<void>((resolve, reject) => {
      updateStatus(
        {
          resource: ModuleId.users,
          id: row.id,
          values: { status },
          meta: { action: "status" },
          successNotification: false,
          errorNotification: false,
        },
        {
          onSuccess: () => resolve(),
          onError: (error) => reject(error),
        },
      );
    });
  }

  function onStatus(row: UserRow, next: string) {
    if (statusAction.submitting) return;
    if (next !== "active" && next !== "disabled") return;
    if (next === row.status) return;
    const recordName = row.display_name || row.account;
    if (next === "disabled") {
      statusAction.run({
        safety: "confirm",
        key: row.id,
        recordName,
        title: t("users.status.disable.confirmTitle", { name: recordName }),
        consequence: t("users.status.disable.consequence"),
        confirmLabel: t("users.status.disable"),
        confirmColor: "red",
        outcome: t("users.status.disabled.outcome"),
        execute: () => setUserStatus(row, "disabled"),
        onSuccess: () => reload(),
      });
      return;
    }
    statusAction.run({
      safety: "immediate",
      key: row.id,
      recordName,
      outcome: t("users.status.enabled.outcome"),
      execute: () => setUserStatus(row, "active"),
      onSuccess: () => reload(),
    });
  }

  const createAction = (
    <CreateListAction resource={ModuleId.users} href="/console/users/new">
      {t("users.create")}
    </CreateListAction>
  );

  const openClaim = (item: PendingFederatedIdentity) => {
    claimForm.setValues({
      mode: "create",
      account: item.account_hint,
      display_name: item.display_name ?? item.account_hint,
      role_id: null,
      user_id: null,
    });
    claimForm.markSaved();
    setClaimFailure(null);
    setClaimTarget(item);
  };

  const closeClaim = () => {
    setClaimTarget(null);
    setClaimFailure(null);
    claimForm.reset();
  };

  async function submitClaim(values: {
    mode: "create" | "existing";
    account: string;
    display_name: string;
    role_id: string | null;
    user_id: string | null;
  }) {
    if (!claimTarget) return;
    try {
      if (values.mode === "existing") {
        await claimPendingFederatedIdentity(claimTarget.id, {
          user_id: values.user_id ?? "",
        });
      } else {
        await claimPendingFederatedIdentity(claimTarget.id, {
          create_user: {
            account: values.account.trim(),
            display_name: values.display_name.trim(),
            email: claimTarget.email,
            role_id: values.role_id ?? "",
          },
        });
      }
      claimForm.markSaved();
      setClaimFailure(null);
      closeClaim();
      await reloadPendingList();
      await reload();
    } catch (err) {
      setClaimFailure(
        saveFailureFrom(
          t,
          err,
          claimForm.applyApiError(err),
          t("common.error.loadFailed"),
        ),
      );
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
      emptyMessage={t("users.list.empty")}
      emptyAction={createAction}
      noMatchMessage={t("users.list.noMatch")}
      onClearFilters={usersQuery.clear}
      head={
        <Table.Tr>
          <Table.Th>{t("users.fields.displayName")}</Table.Th>
          <Table.Th>{t("users.fields.role")}</Table.Th>
          <Table.Th>{t("users.fields.status")}</Table.Th>
          <Table.Th>{t("users.fields.identity")}</Table.Th>
          <Table.Th>{t("users.fields.lastLoginAt")}</Table.Th>
          <Table.Th>{t("users.fields.actions")}</Table.Th>
        </Table.Tr>
      }
    >
      {rows.map((row) => {
        const isSelf = identity?.id === row.id;
        return (
          <Table.Tr key={row.id}>
            <Table.Td>
              <RecordReference
                name={row.display_name || row.account}
                recordKey={row.account}
                href={`/console/users/${row.id}`}
              />
            </Table.Td>
            <Table.Td>
              <UserRoleBadge
                roleName={row.role_name}
                roleKey={row.role_key}
              />
            </Table.Td>
            <Table.Td>
              <SegmentedField
                editable={Boolean(canWrite?.can) && !isSelf}
                size="xs"
                aria-label={
                  row.status === "active"
                    ? t("users.status.active")
                    : t("users.status.disabled")
                }
                data={[
                  { value: "active", label: t("users.status.active") },
                  { value: "disabled", label: t("users.status.disabled") },
                ]}
                value={row.status}
                onChange={(value) => onStatus(row, value)}
              />
            </Table.Td>
            <Table.Td>
              <Text size="sm">{t(`identitySource.${row.identity_source}`)}</Text>
            </Table.Td>
            <Table.Td>{showInstant(row.last_login_at)}</Table.Td>
            <Table.Td>
              <RowActions
                recordName={row.display_name || row.account}
                verbs={[
                  {
                    key: "unfederate",
                    label: t("users.federation.unfederate.title"),
                    hidden: row.identity_source !== "oidc" || !canWrite?.can,
                    safety: "confirm",
                    onClick: () => {
                      unfederateConfirm.open(row);
                      setUnfederatePassword("");
                    },
                  },
                ]}
              />
            </Table.Td>
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

  const listTabs = canWrite?.can
    ? [
        { value: "users", label: t("users.tabs.users"), panel: userTable },
        {
          value: "pending",
          label: (
            <Group gap={6} wrap="nowrap">
              {t("users.pending.title")}
              {pendingBadge}
            </Group>
          ),
          panel: (
            <PendingFederatedIdentityTable list={pendingList} onClaim={openClaim} />
          ),
        },
      ]
    : [];

  const frame = (tabs: ReactNode, body: ReactNode) => (
    <PageChrome
      title={t("users.title")}
      description={t("users.description")}
      actions={createAction}
      fill={Boolean(canWrite?.can)}
      tabs={tabs}
      toolbar={
        !canWrite?.can || activeTab === "users" ? (
          <ListToolbar
            query={usersQuery}
            searchPlaceholder={t("users.search")}
          />
        ) : undefined
      }
    >
      {body}

      <FormDialog
        opened={claimTarget !== null}
        onClose={closeClaim}
        title={t("users.pending.claimTitle")}
        dirty={claimForm.dirty}
        submitting={claimForm.submitting}
        submitLabel={t("users.pending.claim")}
        summary={<FormErrorSummary failure={claimFailure} />}
        onSubmit={() => void claimForm.submit(submitClaim)}
      >
        <Stack gap="sm">
          <SegmentedField
            editable
            fullWidth
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
            {...claimForm.fieldProps("mode")}
            value={claimForm.values.mode}
          />
          {claimForm.values.mode === "existing" ? (
            <RecordPicker
              editable
              label={t("users.pending.claimExisting")}
              adapter={userRecordAdapter({ identitySource: "local" })}
              clearable
              {...claimForm.fieldProps("user_id")}
            />
          ) : (
            <>
              <TextField
                editable
                label={t("users.fields.account")}
                required
                {...claimForm.fieldProps("account")}
              />
              <TextField
                editable
                label={t("users.fields.displayName")}
                required
                {...claimForm.fieldProps("display_name")}
              />
              <RecordPicker
                editable
                label={t("users.fields.role")}
                adapter={roleRecordAdapter()}
                required
                {...claimForm.fieldProps("role_id")}
              />
            </>
          )}
        </Stack>
      </FormDialog>

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
      {statusAction.dialog}
    </PageChrome>
  );

  if (listTabs.length === 0) {
    return frame(undefined, userTable);
  }

  return (
    <PageTabs fill value={activeTab} onChange={setTab} tabs={listTabs}>
      {({ list, panels }) => frame(list, <FillColumn>{panels}</FillColumn>)}
    </PageTabs>
  );
}
