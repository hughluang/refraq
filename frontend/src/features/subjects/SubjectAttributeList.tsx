"use client";

import { Stack, Table } from "@mantine/core";
import { useCan, useNotification, useTranslate } from "@refinedev/core";
import { useCallback, useState } from "react";

import { CreateListAction } from "@/components/access/CreateListAction";
import { ListTable } from "@/components/display/ListTable";
import { RecordReference } from "@/components/display/RecordReference";
import { RowActions } from "@/components/display/RowActions";
import { FormDialog } from "@/components/form/FormDialog";
import {
  FormErrorSummary,
  saveFailureFrom,
  type SaveFailure,
} from "@/components/form/FormErrorSummary";
import { RecordPicker } from "@/components/form/RecordPicker";
import { dictionaryRecordAdapter } from "@/components/form/recordPickerAdapters";
import { SelectField } from "@/components/form/SelectField";
import { useConsoleForm } from "@/components/form/useConsoleForm";
import { SwitchField } from "@/components/form/SwitchField";
import { TextField } from "@/components/form/TextField";
import { PageChrome } from "@/components/layout/PageChrome";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import {
  createSubjectAttribute,
  deleteSubjectAttribute,
  listSubjectAttributes,
  patchSubjectAttribute,
} from "@/features/subjects/api";
import { subjectKeyError, subjectNameError } from "@/features/subjects/rules";
import type { SubjectAttribute, SubjectValueType } from "@/features/subjects/types";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
import { useListQuery } from "@/hooks/useListQuery";
import { problemMessage } from "@/lib/problem";
import type { PageQuery } from "@/lib/pagination";

const PAGE_SIZE = 50;
const VALUE_TYPES: SubjectValueType[] = [
  "string",
  "integer",
  "date",
  "dictionary",
  "user",
];

type Draft = {
  id: string | null;
  key: string;
  name: string;
  description: string;
  valueType: SubjectValueType;
  dictionaryId: string;
  multiValue: boolean;
  multiLocked: boolean;
};

const EMPTY_DRAFT: Draft = {
  id: null,
  key: "",
  name: "",
  description: "",
  valueType: "string",
  dictionaryId: "",
  multiValue: false,
  multiLocked: false,
};

export function SubjectAttributeList() {
  const t = useTranslate();
  const { open } = useNotification();
  const { data: canWrite } = useCan({
    resource: ModuleId.subjectAttributes,
    action: ModuleAction.edit,
  });
  const { data: canDelete } = useCan({
    resource: ModuleId.subjectAttributes,
    action: ModuleAction.delete,
  });
  const query = useListQuery({ search: false });
  const [opened, setOpened] = useState(false);
  const [saveFailure, setSaveFailure] = useState<SaveFailure | null>(null);
  const form = useConsoleForm<Draft>({
    initialValues: EMPTY_DRAFT,
    onValuesChange: () => setSaveFailure(null),
    validate: {
      key: (value, values) => {
        if (values.id) return null;
        const issue = subjectKeyError(value);
        return issue ? t(`subjectAttributes.validation.key.${issue}`) : null;
      },
      name: (value) => {
        const issue = subjectNameError(value);
        return issue ? t(`subjectAttributes.validation.name.${issue}`) : null;
      },
      dictionaryId: (value, values) =>
        values.valueType === "dictionary" && !value.trim()
          ? t("subjectAttributes.validation.dictionary.required")
          : null,
    },
  });

  const fetchPage = useCallback(
    (query: PageQuery) => listSubjectAttributes(query),
    [],
  );
  const list = useConsolePagedList<SubjectAttribute>({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
    page: query.page,
    onPageChange: query.setPage,
  });

  function notifyError(err: unknown) {
    open?.({
      type: "error",
      message: t("subjectAttributes.title"),
      description: problemMessage(t, err, t("common.error.loadFailed")),
    });
  }

  function openCreate() {
    form.setValues(EMPTY_DRAFT);
    form.markSaved();
    setSaveFailure(null);
    setOpened(true);
  }

  function openEdit(row: SubjectAttribute) {
    form.setValues({
      id: row.id,
      key: row.key,
      name: row.name,
      description: row.description ?? "",
      valueType: row.value_type,
      dictionaryId: row.dictionary_id ?? "",
      multiValue: row.multi_value,
      multiLocked: row.multi_value,
    });
    form.markSaved();
    setSaveFailure(null);
    setOpened(true);
  }

  function close() {
    setOpened(false);
    setSaveFailure(null);
    form.reset();
  }

  async function submit(values: Draft) {
    try {
      if (values.id) {
        await patchSubjectAttribute(values.id, {
          name: values.name.trim(),
          description: values.description.trim() || null,
          multi_value: values.multiValue,
        });
      } else {
        await createSubjectAttribute({
          key: values.key,
          name: values.name.trim(),
          description: values.description.trim() || null,
          value_type: values.valueType,
          ...(values.valueType === "dictionary"
            ? { dictionary_id: values.dictionaryId.trim() }
            : {}),
          multi_value: values.multiValue,
        });
      }
      form.markSaved();
      setSaveFailure(null);
      setOpened(false);
      form.reset();
      await list.reload();
    } catch (err) {
      setSaveFailure(
        saveFailureFrom(
          t,
          err,
          form.applyApiError(err),
          t("common.error.loadFailed"),
        ),
      );
    }
  }

  const creating = form.values.id == null;
  const createAction = (
    <CreateListAction
      resource={ModuleId.subjectAttributes}
      onClick={openCreate}
    >
      {t("subjectAttributes.create")}
    </CreateListAction>
  );

  return (
    <PageChrome
      title={t("subjectAttributes.title")}
      description={t("subjectAttributes.description")}
      actions={createAction}
    >
      <ListTable
        list={list}
        columnCount={4}
        emptyMessage={t("subjectAttributes.list.empty")}
        emptyAction={createAction}
        head={
          <Table.Tr>
            <Table.Th>{t("subjectAttributes.fields.name")}</Table.Th>
            <Table.Th>{t("subjectAttributes.fields.valueType")}</Table.Th>
            <Table.Th>{t("subjectAttributes.fields.multiValue")}</Table.Th>
            <Table.Th>{t("subjectAttributes.fields.actions")}</Table.Th>
          </Table.Tr>
        }
      >
        {list.items.map((row) => (
          <Table.Tr key={row.id}>
            <Table.Td>
              <RecordReference name={row.name} recordKey={row.key} />
            </Table.Td>
            <Table.Td>{t(`subjectAttributes.valueType.${row.value_type}`)}</Table.Td>
            <Table.Td>
              {row.multi_value ? t("form.value.yes") : t("form.value.no")}
            </Table.Td>
            <Table.Td>
              <RowActions
                recordName={row.name}
                verbs={[
                  {
                    key: "edit",
                    label: t("subjectAttributes.edit"),
                    hidden: !canWrite?.can,
                    safety: "immediate",
                    onClick: () => openEdit(row),
                  },
                  {
                    key: "delete",
                    label: t("subjectAttributes.delete"),
                    color: "red",
                    hidden: !canDelete?.can,
                    action: {
                      safety: "confirm",
                      recordName: row.name,
                      title: t("subjectAttributes.delete.confirmTitle"),
                      consequence: t("subjectAttributes.delete.consequence"),
                      confirmLabel: t("subjectAttributes.delete"),
                      confirmColor: "red",
                      outcome: t("subjectAttributes.delete.outcome"),
                      execute: () => deleteSubjectAttribute(row.id),
                      onSuccess: () => list.reload(),
                    },
                  },
                ]}
              />
            </Table.Td>
          </Table.Tr>
        ))}
      </ListTable>
      <FormDialog
        opened={opened}
        onClose={close}
        title={creating ? t("subjectAttributes.create") : t("subjectAttributes.edit")}
        dirty={form.dirty}
        submitting={form.submitting}
        submitLabel={t("subjectAttributes.save")}
        summary={<FormErrorSummary failure={saveFailure} />}
        onSubmit={() => void form.submit(submit)}
      >
        <Stack gap="sm">
          <TextField
            editable={creating}
            required
            label={t("subjectAttributes.fields.key")}
            description={t("subjectAttributes.fields.keyHint")}
            {...form.fieldProps("key")}
          />
          <TextField
            editable
            required
            label={t("subjectAttributes.fields.name")}
            {...form.fieldProps("name")}
          />
          <TextField
            editable
            label={t("subjectAttributes.fields.description")}
            {...form.fieldProps("description")}
          />
          <SelectField
            editable={creating}
            label={t("subjectAttributes.fields.valueType")}
            data={VALUE_TYPES.map((value) => ({
              value,
              label: t(`subjectAttributes.valueType.${value}`),
            }))}
            allowDeselect={false}
            {...form.fieldProps("valueType")}
          />
          {form.values.valueType === "dictionary" ? (
            <RecordPicker
              editable={creating}
              required
              label={t("subjectAttributes.fields.dictionaryId")}
              adapter={dictionaryRecordAdapter()}
              {...form.fieldProps("dictionaryId")}
            />
          ) : null}
          <SwitchField
            editable={!form.values.multiLocked}
            label={t("subjectAttributes.fields.multiValue")}
            description={t("subjectAttributes.fields.multiValueHint")}
            {...form.fieldProps("multiValue", { type: "checkbox" })}
          />
        </Stack>
      </FormDialog>
    </PageChrome>
  );
}
