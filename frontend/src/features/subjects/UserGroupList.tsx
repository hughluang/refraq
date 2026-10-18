"use client";

import { Stack, Table } from "@mantine/core";
import { useCan, useNotification, useTranslate } from "@refinedev/core";
import { useCallback, useState } from "react";

import { CreateListAction } from "@/components/access/CreateListAction";
import { ListTable } from "@/components/display/ListTable";
import { ListToolbar } from "@/components/display/ListToolbar";
import { RecordReference } from "@/components/display/RecordReference";
import { RowActions } from "@/components/display/RowActions";
import { FormDialog } from "@/components/form/FormDialog";
import {
  FormErrorSummary,
  saveFailureFrom,
  type SaveFailure,
} from "@/components/form/FormErrorSummary";
import { TextField } from "@/components/form/TextField";
import { useConsoleForm } from "@/components/form/useConsoleForm";
import { PageChrome } from "@/components/layout/PageChrome";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import { createUserGroup, deleteUserGroup, listUserGroups } from "@/features/subjects/api";
import { subjectKeyError, subjectNameError } from "@/features/subjects/rules";
import type { UserGroup } from "@/features/subjects/types";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { useListQuery } from "@/hooks/useListQuery";
import { problemMessage } from "@/lib/problem";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;

export function UserGroupList() {
  const t = useTranslate();
  const { open } = useNotification();
  const { data: canDelete } = useCan({
    resource: ModuleId.userGroups,
    action: ModuleAction.delete,
  });
  const query = useListQuery();
  const [opened, setOpened] = useState(false);
  const [saveFailure, setSaveFailure] = useState<SaveFailure | null>(null);
  const form = useConsoleForm<{ key: string; name: string; description: string }>({
    initialValues: { key: "", name: "", description: "" },
    onValuesChange: () => setSaveFailure(null),
    validate: {
      key: (value) => {
        const issue = subjectKeyError(value);
        return issue ? t(`userGroups.validation.key.${issue}`) : null;
      },
      name: (value) => {
        const issue = subjectNameError(value);
        return issue ? t(`userGroups.validation.name.${issue}`) : null;
      },
    },
  });
  const fetchPage = useCallback(
    (page: PageQuery) =>
      listUserGroups({ ...page, q: query.search || undefined }),
    [query.search],
  );
  const list = useConsolePagedList<UserGroup>({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
    resetDeps: [query.search],
    filtered: query.isFiltered,
    page: query.page,
    onPageChange: query.setPage,
  });

  function notifyError(err: unknown) {
    open?.({
      type: "error",
      message: t("userGroups.title"),
      description: problemMessage(t, err, t("common.error.loadFailed")),
    });
  }

  function close() {
    setOpened(false);
    setSaveFailure(null);
    form.reset();
  }

  async function submitCreate(values: { key: string; name: string; description: string }) {
    try {
      await createUserGroup({
        key: values.key,
        name: values.name.trim(),
        description: values.description.trim() || null,
      });
      form.markSaved();
      setSaveFailure(null);
      setOpened(false);
      form.reset();
      await list.reload();
    } catch (err) {
      setSaveFailure(
        saveFailureFrom(t, err, form.applyApiError(err), t("common.error.loadFailed")),
      );
    }
  }

  const createAction = (
    <CreateListAction
      resource={ModuleId.userGroups}
      onClick={() => setOpened(true)}
    >
      {t("userGroups.create")}
    </CreateListAction>
  );

  return (
    <PageChrome
      title={t("userGroups.title")}
      description={t("userGroups.description")}
      actions={createAction}
      toolbar={
        <ListToolbar query={query} searchPlaceholder={t("userGroups.search")} />
      }
    >
      <Stack gap="sm">
        <ListTable
          list={list}
          columnCount={3}
          emptyMessage={t("userGroups.list.empty")}
          emptyAction={createAction}
          noMatchMessage={t("userGroups.list.noMatch")}
          onClearFilters={query.clear}
          head={
            <Table.Tr>
              <Table.Th>{t("userGroups.fields.name")}</Table.Th>
              <Table.Th>{t("userGroups.fields.members")}</Table.Th>
              <Table.Th>{t("userGroups.fields.actions")}</Table.Th>
            </Table.Tr>
          }
        >
          {list.items.map((row) => (
            <Table.Tr key={row.id}>
              <Table.Td>
                <RecordReference
                  name={row.name}
                  recordKey={row.key}
                  href={`/console/user-groups/${row.id}`}
                />
              </Table.Td>
              <Table.Td>{row.member_count}</Table.Td>
              <Table.Td>
                <RowActions
                  recordName={row.name}
                  verbs={[
                    {
                      key: "delete",
                      label: t("userGroups.delete"),
                      color: "red",
                      hidden: !canDelete?.can,
                      action: {
                        safety: "confirm",
                        recordName: row.name,
                        title: t("userGroups.delete.confirmTitle"),
                        consequence: t("userGroups.delete.consequence"),
                        confirmLabel: t("userGroups.delete"),
                        confirmColor: "red",
                        outcome: t("userGroups.delete.outcome"),
                        execute: () => deleteUserGroup(row.id),
                        onSuccess: () => list.reload(),
                      },
                    },
                  ]}
                />
              </Table.Td>
            </Table.Tr>
          ))}
        </ListTable>
      </Stack>
      <FormDialog
        opened={opened}
        onClose={close}
        title={t("userGroups.create")}
        dirty={form.dirty}
        submitting={form.submitting}
        submitLabel={t("userGroups.create")}
        summary={<FormErrorSummary failure={saveFailure} />}
        onSubmit={() => void form.submit(submitCreate)}
      >
        <Stack gap="sm">
          <TextField
            editable
            required
            label={t("userGroups.fields.key")}
            description={t("userGroups.fields.keyHint")}
            {...form.fieldProps("key")}
          />
          <TextField
            editable
            required
            label={t("userGroups.fields.name")}
            {...form.fieldProps("name")}
          />
          <TextField
            editable
            label={t("userGroups.fields.description")}
            {...form.fieldProps("description")}
          />
        </Stack>
      </FormDialog>
    </PageChrome>
  );
}
