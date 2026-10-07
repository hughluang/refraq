"use client";

import { Button, Group, Modal, Stack, Table, TextInput } from "@mantine/core";
import { useCan, useNotification, useTranslate } from "@refinedev/core";
import Link from "next/link";
import { useCallback, useState } from "react";

import { ListTable } from "@/components/display/ListTable";
import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import { TextField } from "@/components/form/TextField";
import { PageChrome } from "@/components/layout/PageChrome";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import { createUserGroup, deleteUserGroup, listUserGroups } from "@/features/subjects/api";
import { subjectKeyError, subjectNameError } from "@/features/subjects/rules";
import type { UserGroup } from "@/features/subjects/types";
import { useConfirmAction } from "@/hooks/useConfirmAction";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { ApiError } from "@/lib/api";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;

export function UserGroupList() {
  const t = useTranslate();
  const { open } = useNotification();
  const { data: canWrite } = useCan({
    resource: ModuleId.userGroups,
    action: ModuleAction.create,
  });
  const [query, setQuery] = useState("");
  const [opened, setOpened] = useState(false);
  const [key, setKey] = useState("");
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [busy, setBusy] = useState(false);
  const deleteConfirm = useConfirmAction<UserGroup>();

  const fetchPage = useCallback(
    (page: PageQuery) => listUserGroups({ ...page, q: query.trim() || undefined }),
    [query],
  );
  const list = useConsolePagedList<UserGroup>({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
    resetDeps: [query],
    filtered: Boolean(query.trim()),
  });

  function notifyError(err: unknown) {
    open?.({
      type: "error",
      message: t("userGroups.title"),
      description: err instanceof ApiError ? err.detail : t("common.error.loadFailed"),
    });
  }

  async function submitCreate() {
    if (subjectKeyError(key) || subjectNameError(name)) return;
    setBusy(true);
    try {
      await createUserGroup({
        key,
        name: name.trim(),
        description: description.trim() || null,
      });
      setOpened(false);
      setKey("");
      setName("");
      setDescription("");
      await list.reload();
    } catch (err) {
      notifyError(err);
    } finally {
      setBusy(false);
    }
  }

  async function confirmDelete() {
    const pending = deleteConfirm.pending;
    if (!pending) return;
    setBusy(true);
    try {
      await deleteUserGroup(pending.id);
      deleteConfirm.close();
      await list.reload();
    } catch (err) {
      notifyError(err);
    } finally {
      setBusy(false);
    }
  }

  const keyIssue = subjectKeyError(key);
  const nameIssue = subjectNameError(name);

  return (
    <PageChrome
      title={t("userGroups.title")}
      description={t("userGroups.description")}
      actions={
        canWrite?.can ? (
          <Button size="sm" onClick={() => setOpened(true)}>
            {t("userGroups.create")}
          </Button>
        ) : null
      }
    >
      <Stack gap="sm">
        <TextInput
          label={t("userGroups.search")}
          value={query}
          onChange={(event) => setQuery(event.currentTarget.value)}
        />
        <ListTable
          list={list}
          columnCount={4}
          head={
            <Table.Tr>
              <Table.Th>{t("userGroups.fields.key")}</Table.Th>
              <Table.Th>{t("userGroups.fields.name")}</Table.Th>
              <Table.Th>{t("userGroups.fields.members")}</Table.Th>
              <Table.Th>{t("userGroups.fields.actions")}</Table.Th>
            </Table.Tr>
          }
        >
          {list.items.map((row) => (
            <Table.Tr key={row.id}>
              <Table.Td>{row.key}</Table.Td>
              <Table.Td>{row.name}</Table.Td>
              <Table.Td>{row.member_count}</Table.Td>
              <Table.Td>
                <Group gap="xs">
                  <Button
                    component={Link}
                    href={`/console/user-groups/${row.id}`}
                    size="xs"
                    variant="light"
                  >
                    {t("userGroups.show")}
                  </Button>
                  {canWrite?.can ? (
                    <Button
                      size="xs"
                      variant="light"
                      color="red"
                      onClick={() => deleteConfirm.open(row)}
                    >
                      {t("userGroups.delete")}
                    </Button>
                  ) : null}
                </Group>
              </Table.Td>
            </Table.Tr>
          ))}
        </ListTable>
      </Stack>
      <Modal
        opened={opened}
        onClose={() => setOpened(false)}
        title={t("userGroups.create")}
      >
        <Stack gap="sm">
          <TextField
            editable
            required
            label={t("userGroups.fields.key")}
            description={t("userGroups.fields.keyHint")}
            value={key}
            onChange={(event) => setKey(event.currentTarget.value)}
            error={
              key && keyIssue
                ? t(`userGroups.validation.key.${keyIssue}`)
                : undefined
            }
          />
          <TextField
            editable
            required
            label={t("userGroups.fields.name")}
            value={name}
            onChange={(event) => setName(event.currentTarget.value)}
            error={
              name && nameIssue
                ? t(`userGroups.validation.name.${nameIssue}`)
                : undefined
            }
          />
          <TextField
            editable
            label={t("userGroups.fields.description")}
            value={description}
            onChange={(event) => setDescription(event.currentTarget.value)}
          />
          <Group justify="flex-end">
            <Button variant="default" onClick={() => setOpened(false)}>
              {t("common.cancel")}
            </Button>
            <Button
              loading={busy}
              disabled={Boolean(subjectKeyError(key) || subjectNameError(name))}
              onClick={() => void submitCreate()}
            >
              {t("userGroups.create")}
            </Button>
          </Group>
        </Stack>
      </Modal>
      <ConfirmActionModal
        opened={deleteConfirm.opened}
        onClose={deleteConfirm.close}
        title={t("userGroups.delete.confirmTitle")}
        body={t("userGroups.delete.confirmBody", {
          name: deleteConfirm.pending?.name ?? "",
        })}
        confirmColor="red"
        loading={busy}
        onConfirm={() => void confirmDelete()}
      />
    </PageChrome>
  );
}
