"use client";

import {
  Button,
  Group,
  Modal,
  Stack,
  Table,
} from "@mantine/core";
import { useCan, useNotification, useTranslate } from "@refinedev/core";
import { useCallback, useState } from "react";

import { ListTable } from "@/components/display/ListTable";
import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import { SelectField } from "@/components/form/SelectField";
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
import { useConfirmAction } from "@/hooks/useConfirmAction";
import { useConsolePagedList } from "@/hooks/useConsolePagedList";
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
    action: ModuleAction.create,
  });
  const [draft, setDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState(false);
  const deleteConfirm = useConfirmAction<SubjectAttribute>();

  const fetchPage = useCallback(
    (query: PageQuery) => listSubjectAttributes(query),
    [],
  );
  const list = useConsolePagedList<SubjectAttribute>({
    pageSize: PAGE_SIZE,
    fetch: fetchPage,
  });

  function notifyError(err: unknown) {
    open?.({
      type: "error",
      message: t("subjectAttributes.title"),
      description: problemMessage(t, err, t("common.error.loadFailed")),
    });
  }

  function openEdit(row: SubjectAttribute) {
    setDraft({
      id: row.id,
      key: row.key,
      name: row.name,
      description: row.description ?? "",
      valueType: row.value_type,
      dictionaryId: row.dictionary_id ?? "",
      multiValue: row.multi_value,
      multiLocked: row.multi_value,
    });
  }

  async function submit() {
    if (!draft) return;
    if (subjectNameError(draft.name)) return;
    if (!draft.id && subjectKeyError(draft.key)) return;
    if (draft.valueType === "dictionary" && !draft.dictionaryId.trim()) return;
    setBusy(true);
    try {
      if (draft.id) {
        await patchSubjectAttribute(draft.id, {
          name: draft.name.trim(),
          description: draft.description.trim() || null,
          multi_value: draft.multiValue,
        });
      } else {
        await createSubjectAttribute({
          key: draft.key,
          name: draft.name.trim(),
          description: draft.description.trim() || null,
          value_type: draft.valueType,
          ...(draft.valueType === "dictionary"
            ? { dictionary_id: draft.dictionaryId.trim() }
            : {}),
          multi_value: draft.multiValue,
        });
      }
      setDraft(null);
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
      await deleteSubjectAttribute(pending.id);
      deleteConfirm.close();
      await list.reload();
    } catch (err) {
      notifyError(err);
    } finally {
      setBusy(false);
    }
  }

  const creating = draft != null && draft.id == null;
  const keyIssue = draft ? subjectKeyError(draft.key) : null;
  const nameIssue = draft ? subjectNameError(draft.name) : null;
  const dictionaryMissing =
    draft?.valueType === "dictionary" && !draft.dictionaryId.trim();

  return (
    <PageChrome
      title={t("subjectAttributes.title")}
      description={t("subjectAttributes.description")}
      actions={
        canWrite?.can ? (
          <Button size="sm" onClick={() => setDraft(EMPTY_DRAFT)}>
            {t("subjectAttributes.create")}
          </Button>
        ) : null
      }
    >
      <ListTable
        list={list}
        columnCount={5}
        head={
          <Table.Tr>
            <Table.Th>{t("subjectAttributes.fields.key")}</Table.Th>
            <Table.Th>{t("subjectAttributes.fields.name")}</Table.Th>
            <Table.Th>{t("subjectAttributes.fields.valueType")}</Table.Th>
            <Table.Th>{t("subjectAttributes.fields.multiValue")}</Table.Th>
            <Table.Th>{t("subjectAttributes.fields.actions")}</Table.Th>
          </Table.Tr>
        }
      >
        {list.items.map((row) => (
          <Table.Tr key={row.id}>
            <Table.Td>{row.key}</Table.Td>
            <Table.Td>{row.name}</Table.Td>
            <Table.Td>{t(`subjectAttributes.valueType.${row.value_type}`)}</Table.Td>
            <Table.Td>
              {row.multi_value ? t("form.value.yes") : t("form.value.no")}
            </Table.Td>
            <Table.Td>
              {canWrite?.can ? (
                <Group gap="xs">
                  <Button size="xs" variant="light" onClick={() => openEdit(row)}>
                    {t("subjectAttributes.edit")}
                  </Button>
                  <Button
                    size="xs"
                    variant="light"
                    color="red"
                    onClick={() => deleteConfirm.open(row)}
                  >
                    {t("subjectAttributes.delete")}
                  </Button>
                </Group>
              ) : null}
            </Table.Td>
          </Table.Tr>
        ))}
      </ListTable>
      <Modal
        opened={draft != null}
        onClose={() => setDraft(null)}
        title={creating ? t("subjectAttributes.create") : t("subjectAttributes.edit")}
      >
        {draft ? (
          <Stack gap="sm">
            <TextField
              editable={creating}
              required
              label={t("subjectAttributes.fields.key")}
              description={t("subjectAttributes.fields.keyHint")}
              value={draft.key}
              onChange={(event) =>
                setDraft({ ...draft, key: event.currentTarget.value })
              }
              error={
                creating && draft.key && keyIssue
                  ? t(`subjectAttributes.validation.key.${keyIssue}`)
                  : undefined
              }
            />
            <TextField
              editable
              required
              label={t("subjectAttributes.fields.name")}
              value={draft.name}
              onChange={(event) =>
                setDraft({ ...draft, name: event.currentTarget.value })
              }
              error={
                draft.name && nameIssue
                  ? t(`subjectAttributes.validation.name.${nameIssue}`)
                  : undefined
              }
            />
            <TextField
              editable
              label={t("subjectAttributes.fields.description")}
              value={draft.description}
              onChange={(event) =>
                setDraft({ ...draft, description: event.currentTarget.value })
              }
            />
            <SelectField
              editable={creating}
              label={t("subjectAttributes.fields.valueType")}
              data={VALUE_TYPES.map((value) => ({
                value,
                label: t(`subjectAttributes.valueType.${value}`),
              }))}
              value={draft.valueType}
              allowDeselect={false}
              onChange={(value) =>
                setDraft({
                  ...draft,
                  valueType: (value ?? draft.valueType) as SubjectValueType,
                })
              }
            />
            {draft.valueType === "dictionary" ? (
              <TextField
                editable={creating}
                required
                label={t("subjectAttributes.fields.dictionaryId")}
                value={draft.dictionaryId}
                onChange={(event) =>
                  setDraft({ ...draft, dictionaryId: event.currentTarget.value })
                }
              />
            ) : null}
            <SwitchField
              editable={!draft.multiLocked}
              label={t("subjectAttributes.fields.multiValue")}
              description={t("subjectAttributes.fields.multiValueHint")}
              checked={draft.multiValue}
              onChange={(event) =>
                setDraft({ ...draft, multiValue: event.currentTarget.checked })
              }
            />
            <Group justify="flex-end">
              <Button variant="default" onClick={() => setDraft(null)}>
                {t("common.cancel")}
              </Button>
              <Button
                loading={busy}
                disabled={
                  Boolean(nameIssue) ||
                  (creating && Boolean(keyIssue)) ||
                  Boolean(dictionaryMissing)
                }
                onClick={() => void submit()}
              >
                {t("subjectAttributes.save")}
              </Button>
            </Group>
          </Stack>
        ) : null}
      </Modal>
      <ConfirmActionModal
        opened={deleteConfirm.opened}
        onClose={deleteConfirm.close}
        title={t("subjectAttributes.delete.confirmTitle")}
        body={t("subjectAttributes.delete.confirmBody", {
          name: deleteConfirm.pending?.name ?? "",
        })}
        confirmColor="red"
        loading={busy}
        onConfirm={() => void confirmDelete()}
      />
    </PageChrome>
  );
}
