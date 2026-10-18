"use client";

import { Stack, Table, Text } from "@mantine/core";
import { useCan, useNotification, useTranslate } from "@refinedev/core";
import { useCallback, useState } from "react";

import { CreateListAction } from "@/components/access/CreateListAction";
import { Instant } from "@/components/display/Instant";
import { FormDialog } from "@/components/form/FormDialog";
import {
  FormErrorSummary,
  saveFailureFrom,
  type SaveFailure,
} from "@/components/form/FormErrorSummary";
import { TextareaField } from "@/components/form/TextareaField";
import { TextField } from "@/components/form/TextField";
import { useConsoleForm } from "@/components/form/useConsoleForm";
import { ListTable } from "@/components/display/ListTable";
import { ListToolbar } from "@/components/display/ListToolbar";
import { RecordReference } from "@/components/display/RecordReference";
import { RowActions } from "@/components/display/RowActions";
import { PageChrome } from "@/components/layout/PageChrome";
import {
  createBusinessDomain,
  deleteBusinessDomain,
  listBusinessDomains,
  patchBusinessDomain,
} from "@/features/business-domains/api";
import type { BusinessDomain } from "@/features/business-domains/types";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { useListQuery } from "@/hooks/useListQuery";
import { problemMessage } from "@/lib/problem";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 100;

type CreateForm = {
  code: string;
  name: string;
  description: string;
};

type EditForm = {
  name: string;
  description: string;
};

export function BusinessDomainList() {
  const t = useTranslate();
  const { open } = useNotification();
  const { data: canEdit } = useCan({
    resource: ModuleId.businessDomains,
    action: ModuleAction.edit,
  });
  const { data: canDelete } = useCan({
    resource: ModuleId.businessDomains,
    action: ModuleAction.delete,
  });

  const query = useListQuery();
  const [createOpen, setCreateOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<BusinessDomain | null>(null);
  const [createFailure, setCreateFailure] = useState<SaveFailure | null>(null);
  const [editFailure, setEditFailure] = useState<SaveFailure | null>(null);

  const createForm = useConsoleForm<CreateForm>({
    initialValues: { code: "", name: "", description: "" },
    onValuesChange: () => setCreateFailure(null),
  });
  const editForm = useConsoleForm<EditForm>({
    initialValues: { name: "", description: "" },
    onValuesChange: () => setEditFailure(null),
  });

  const fetchPage = useCallback(
    (page: PageQuery) =>
      listBusinessDomains({
        q: query.search || undefined,
        ...page,
      }),
    [query.search],
  );

  const list = useConsolePagedList({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
    resetDeps: [query.search],
    filtered: query.isFiltered,
    page: query.page,
    onPageChange: query.setPage,
  });
  const { items, reload } = list;

  const closeCreate = () => {
    setCreateOpen(false);
    setCreateFailure(null);
    createForm.reset();
  };

  const closeEdit = () => {
    setEditTarget(null);
    setEditFailure(null);
    editForm.reset();
  };

  const submitCreate = async (values: CreateForm) => {
    try {
      await createBusinessDomain({
        code: values.code.trim(),
        name: values.name.trim(),
        description: values.description.trim() || null,
      });
      createForm.markSaved();
      setCreateFailure(null);
      setCreateOpen(false);
      createForm.reset();
      open?.({
        type: "success",
        message: t("businessDomains.create.success"),
      });
      await reload();
    } catch (err) {
      setCreateFailure(
        saveFailureFrom(t, err, createForm.applyApiError(err), String(err)),
      );
    }
  };

  const submitEdit = async (values: EditForm) => {
    if (!editTarget) return;
    try {
      await patchBusinessDomain(editTarget.id, {
        name: values.name.trim(),
        description: values.description.trim() || null,
      });
      editForm.markSaved();
      setEditFailure(null);
      setEditTarget(null);
      open?.({
        type: "success",
        message: t("businessDomains.update.success"),
      });
      await reload();
    } catch (err) {
      setEditFailure(
        saveFailureFrom(t, err, editForm.applyApiError(err), String(err)),
      );
    }
  };

  const createAction = (
    <CreateListAction
      resource={ModuleId.businessDomains}
      onClick={() => setCreateOpen(true)}
    >
      {t("businessDomains.create")}
    </CreateListAction>
  );

  return (
    <PageChrome
      title={t("businessDomains.title")}
      description={t("businessDomains.description")}
      actions={createAction}
      toolbar={
        <ListToolbar
          query={query}
          searchPlaceholder={t("businessDomains.search")}
        />
      }
    >
      <ListTable
        list={list}
        columnCount={4}
        emptyMessage={t("businessDomains.list.empty")}
        emptyAction={createAction}
        noMatchMessage={t("businessDomains.list.noMatch")}
        onClearFilters={query.clear}
        head={
          <Table.Tr>
            <Table.Th>{t("businessDomains.fields.name")}</Table.Th>
            <Table.Th>{t("businessDomains.fields.description")}</Table.Th>
            <Table.Th>{t("businessDomains.fields.updatedAt")}</Table.Th>
            <Table.Th />
          </Table.Tr>
        }
      >
        {items.map((row) => (
          <Table.Tr key={row.id}>
            <Table.Td>
              <RecordReference name={row.name} recordKey={row.code} />
            </Table.Td>
            <Table.Td>
              <Text size="sm" c="dimmed" lineClamp={2}>
                {row.description || "—"}
              </Text>
            </Table.Td>
            <Table.Td>
              <Text size="sm" c="dimmed">
                <Instant value={row.updated_at} />
              </Text>
            </Table.Td>
            <Table.Td>
              <RowActions
                recordName={row.name}
                verbs={[
                  {
                    key: "edit",
                    label: t("actions.edit"),
                    hidden: !canEdit?.can,
                    safety: "immediate",
                    onClick: () => {
                      setEditTarget(row);
                      editForm.setValues({
                        name: row.name,
                        description: row.description ?? "",
                      });
                      editForm.markSaved();
                      setEditFailure(null);
                    },
                  },
                  {
                    key: "delete",
                    label: t("actions.delete"),
                    color: "red",
                    hidden: !canDelete?.can,
                    action: {
                      safety: "confirm",
                      recordName: row.name,
                      title: t("businessDomains.delete.confirmTitle"),
                      consequence: t("businessDomains.delete.consequence"),
                      confirmLabel: t("actions.delete"),
                      confirmColor: "red",
                      outcome: t("businessDomains.delete.success"),
                      execute: () => deleteBusinessDomain(row.id),
                      onSuccess: () => reload(),
                    },
                  },
                ]}
              />
            </Table.Td>
          </Table.Tr>
        ))}
      </ListTable>

      <FormDialog
        opened={createOpen}
        onClose={closeCreate}
        title={t("businessDomains.create.title")}
        dirty={createForm.dirty}
        submitting={createForm.submitting}
        submitLabel={t("businessDomains.create.submit")}
        summary={<FormErrorSummary failure={createFailure} />}
        onSubmit={() => void createForm.submit(submitCreate)}
      >
        <Stack>
          <TextField
            label={t("businessDomains.fields.code")}
            required
            editable
            {...createForm.fieldProps("code")}
          />
          <TextField
            label={t("businessDomains.fields.name")}
            required
            editable
            {...createForm.fieldProps("name")}
          />
          <TextareaField
            label={t("businessDomains.fields.description")}
            editable
            {...createForm.fieldProps("description")}
            minRows={2}
          />
        </Stack>
      </FormDialog>

      <FormDialog
        opened={editTarget != null}
        onClose={closeEdit}
        title={t("businessDomains.edit.title")}
        dirty={editForm.dirty}
        submitting={editForm.submitting}
        submitLabel={t("businessDomains.edit.submit")}
        summary={<FormErrorSummary failure={editFailure} />}
        onSubmit={() => void editForm.submit(submitEdit)}
      >
        <Stack>
          <TextField
            label={t("businessDomains.fields.code")}
            editable={false}
            value={editTarget?.code ?? ""}
          />
          <TextField
            label={t("businessDomains.fields.name")}
            required
            editable
            {...editForm.fieldProps("name")}
          />
          <TextareaField
            label={t("businessDomains.fields.description")}
            editable
            {...editForm.fieldProps("description")}
            minRows={2}
          />
        </Stack>
      </FormDialog>
    </PageChrome>
  );
}
