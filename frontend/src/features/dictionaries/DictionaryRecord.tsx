"use client";

import { Badge, Button, Group, Stack, Table, Text } from "@mantine/core";
import { useCan, useNotification, useTranslate } from "@refinedev/core";
import {
  FormErrorSummary,
  saveFailureFrom,
  type SaveFailure,
} from "@/components/form/FormErrorSummary";
import { useConsoleForm } from "@/components/form/useConsoleForm";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { suppressLeaveGuard } from "@/components/navigation/leaveGuard";
import { useConsoleNavigation } from "@/components/navigation/useConsoleNavigation";
import { useCallback, useEffect, useState } from "react";

import { ListTable } from "@/components/display/ListTable";
import { RecordReference } from "@/components/display/RecordReference";
import { useConsoleMutation } from "@/components/feedback/useConsoleMutation";
import { localListSession } from "@/lib/list-state";
import { HeaderAction, HeaderActions } from "@/components/layout/HeaderActions";
import { PageChrome } from "@/components/layout/PageChrome";
import { DictionaryFormFields } from "@/features/dictionaries/DictionaryFormFields";
import { DictionaryStatusBadge } from "@/features/dictionaries/DictionaryStatusBadge";
import {
  createDictionary,
  deleteDictionary,
  getDictionary,
  patchDictionary,
} from "@/features/dictionaries/api";
import {
  EMPTY_DICTIONARY_FORM,
  dictionaryFormErrors,
  entriesFromForm,
  formFromDictionary,
} from "@/features/dictionaries/dictionaryForm";
import type { Dictionary, DictionaryFormValues } from "@/features/dictionaries/types";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import { problemMessage } from "@/lib/problem";

const DICTIONARY_FORM_ID = "dictionary-record-form";

type Props =
  | { mode: "create" }
  | { mode: "show" | "edit"; dictionaryId: string };

type ExistingProps = {
  mode: "show" | "edit";
  dictionaryId: string;
};

export function DictionaryRecord(props: Props) {
  if (props.mode === "create") {
    return <DictionaryCreateForm />;
  }
  return (
    <ExistingDictionaryRecord
      mode={props.mode}
      dictionaryId={props.dictionaryId}
    />
  );
}

function DictionaryCreateForm() {
  const t = useTranslate();
  const { open } = useNotification();
  const [saveFailure, setSaveFailure] = useState<SaveFailure | null>(null);
  const form = useConsoleForm<DictionaryFormValues>({
    initialValues: EMPTY_DICTIONARY_FORM,
    onValuesChange: () => setSaveFailure(null),
    validate: (values) => dictionaryFormErrors(values, t),
  });

  const submit = async (values: DictionaryFormValues) => {
    try {
      const description = values.description.trim();
      const created = await createDictionary({
        name: values.name.trim(),
        display_name: values.display_name.trim(),
        ...(description ? { description } : {}),
        entries: entriesFromForm(values.entries),
      });
      form.markSaved();
      suppressLeaveGuard();
      open?.({ type: "success", message: t("dictionaries.create.success") });
      window.location.replace(
        `/console/dictionaries/${created.dictionary.id}/edit`,
      );
    } catch (err) {
      setSaveFailure(
        saveFailureFrom(t, err, form.applyApiError(err), String(err)),
      );
    }
  };

  return (
    <PageChrome
      title={t("dictionaries.create.title")}
      actions={
        <HeaderActions
          standard={
            <>
              <Button
                component={ConsoleLink}
                href="/console/dictionaries"
                variant="default"
                size="sm"
              >
                {t("common.cancel")}
              </Button>
              <HeaderAction primary>
                <Button
                  type="submit"
                  form={DICTIONARY_FORM_ID}
                  size="sm"
                  loading={form.submitting}
                >
                  {t("dictionaries.create.submit")}
                </Button>
              </HeaderAction>
            </>
          }
        />
      }
    >
      <form
        id={DICTIONARY_FORM_ID}
        noValidate
        onSubmit={form.onSubmit((values) => submit(values))}
      >
        <Stack gap="sm">
          <FormErrorSummary failure={saveFailure} />
          <DictionaryFormFields form={form} editable nameEditable />
        </Stack>
      </form>
    </PageChrome>
  );
}

function ExistingDictionaryRecord({ mode, dictionaryId }: ExistingProps) {
  const t = useTranslate();
  const { replace } = useConsoleNavigation();
  const { open } = useNotification();
  const { data: canWrite } = useCan({
    resource: ModuleId.dictionaries,
    action: ModuleAction.edit,
  });
  const [record, setRecord] = useState<Dictionary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const recordAction = useConsoleMutation();
  const [saveFailure, setSaveFailure] = useState<SaveFailure | null>(null);
  const form = useConsoleForm<DictionaryFormValues>({
    initialValues: EMPTY_DICTIONARY_FORM,
    onValuesChange: () => setSaveFailure(null),
    validate: (values) => dictionaryFormErrors(values, t),
  });

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await getDictionary(dictionaryId);
      setRecord(response.dictionary);
      form.setValues(formFromDictionary(response.dictionary));
      form.markSaved();
    } catch (err) {
      setRecord(null);
      setError(problemMessage(t, err, String(err)));
    } finally {
      setLoading(false);
    }
  }, [dictionaryId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (mode !== "edit") return;
    if (canWrite?.can !== false) return;
    suppressLeaveGuard();
    replace(`/console/dictionaries/${dictionaryId}`);
  }, [canWrite?.can, dictionaryId, mode, replace]);

  const notifyError = (err: unknown, fallback: string) => {
    open?.({
      type: "error",
      message: problemMessage(t, err, fallback),
    });
  };

  const fieldsWritable = mode === "edit" && Boolean(canWrite?.can);
  const dirty = form.isDirty();
  const deprecated = record?.deprecated_at != null;
  const inUse = (record?.usages?.length ?? 0) > 0;

  const submit = async (values: DictionaryFormValues) => {
    try {
      const description = values.description.trim();
      await patchDictionary(dictionaryId, {
        display_name: values.display_name.trim(),
        description: description || null,
        entries: entriesFromForm(values.entries),
      });
      form.markSaved();
      setSaveFailure(null);
      open?.({ type: "success", message: t("dictionaries.update.success") });
      await load();
    } catch (err) {
      setSaveFailure(
        saveFailureFrom(
          t,
          err,
          form.applyApiError(err),
          t("dictionaries.update.failed"),
        ),
      );
    }
  };

  function onDelete() {
    const name = record?.display_name ?? "";
    recordAction.run({
      safety: "confirm",
      key: "delete",
      recordName: name,
      title: t("dictionaries.delete.confirmTitle"),
      consequence: t("dictionaries.delete.consequence"),
      confirmLabel: t("actions.delete"),
      confirmColor: "red",
      outcome: t("dictionaries.delete.success"),
      execute: async () => {
        await deleteDictionary(dictionaryId);
        suppressLeaveGuard();
        replace("/console/dictionaries");
      },
    });
  }

  function onDeprecate() {
    const name = record?.display_name ?? "";
    recordAction.run({
      safety: "confirm",
      key: "deprecate",
      recordName: name,
      title: t("dictionaries.deprecate.confirmTitle"),
      consequence: t("dictionaries.deprecate.consequence"),
      confirmLabel: t("dictionaries.deprecate"),
      confirmColor: "red",
      outcome: t("dictionaries.deprecate.success"),
      execute: () => patchDictionary(dictionaryId, { deprecated: true }),
      onSuccess: () => load(),
    });
  }

  function onRestore() {
    const name = record?.display_name ?? "";
    recordAction.run({
      safety: "undoable",
      key: "restore",
      recordName: name,
      outcome: t("dictionaries.restore.success"),
      execute: () => patchDictionary(dictionaryId, { deprecated: false }),
      undo: () => patchDictionary(dictionaryId, { deprecated: true }),
      onSuccess: () => load(),
    });
  }

  if (loading) {
    return <PageChrome title={t("dictionaries.title")} status="loading" />;
  }

  if (error) {
    return (
      <PageChrome
        title={t("dictionaries.title")}
        status="error"
        errorMessage={error}
        onRetry={() => void load()}
      />
    );
  }

  if (mode === "edit" && canWrite?.can === false) {
    return <PageChrome title={t("dictionaries.edit.title")} status="loading" />;
  }

  const recordTitle = record?.display_name;
  const title = t("dictionaries.title");

  const navigationActions = (
    <Group gap="xs" wrap="nowrap" aria-label={t("dictionaries.actions.navigation")}>
      <Button component={ConsoleLink} href="/console/dictionaries" variant="default" size="sm">
        {t("dictionaries.backToList")}
      </Button>
      <Button variant="default" size="sm" onClick={() => void load()}>
        {t("jobs.refresh")}
      </Button>
    </Group>
  );
  const lifecycleActions = canWrite?.can ? (
      <Group gap="xs" wrap="nowrap" aria-label={t("dictionaries.actions.lifecycle")}>
        {deprecated ? (
          <Button
            size="sm"
            variant="light"
            loading={busy || recordAction.isSubmitting("restore")}
            disabled={dirty}
            onClick={onRestore}
          >
            {t("dictionaries.restore")}
          </Button>
        ) : (
          <Button
            size="sm"
            variant="light"
            color="red"
            loading={busy || recordAction.isSubmitting("deprecate")}
            disabled={dirty}
            onClick={onDeprecate}
          >
            {t("dictionaries.deprecate")}
          </Button>
        )}
      </Group>
  ) : null;
  const showEdit = mode === "show" && Boolean(canWrite?.can);
  const showDelete = !inUse && Boolean(canWrite?.can);
  const showSave = mode !== "show";
  const standardActions = showEdit || showDelete || showSave ? (
      <Group gap="xs" wrap="nowrap" aria-label={t("dictionaries.actions.standard")}>
        {mode === "show" && canWrite?.can ? (
          <Button
            component={ConsoleLink}
            href={`/console/dictionaries/${dictionaryId}/edit`}
            size="sm"
            variant="light"
          >
            {t("actions.edit")}
          </Button>
        ) : null}
        {showDelete ? (
          <Button
            size="sm"
            color="red"
            variant="light"
            loading={recordAction.isSubmitting("delete")}
            onClick={onDelete}
          >
            {t("actions.delete")}
          </Button>
        ) : null}
        {showSave ? (
          <Button
            component={ConsoleLink}
            href={`/console/dictionaries/${dictionaryId}`}
            variant="default"
            size="sm"
          >
            {t("common.cancel")}
          </Button>
        ) : null}
        {showSave ? (
          <HeaderAction primary>
            <Button type="submit" form={DICTIONARY_FORM_ID} size="sm" loading={form.submitting}>
              {t("dictionaries.edit.submit")}
            </Button>
          </HeaderAction>
        ) : null}
      </Group>
  ) : null;

  const headerActions = (
    <HeaderActions
      navigation={navigationActions}
      lifecycle={lifecycleActions}
      standard={standardActions}
    />
  );

  const usages = record?.usages ?? [];
  const body = (
    <Stack>
      <DictionaryFormFields
        form={form}
        editable={fieldsWritable}
        nameEditable={false}
      />
      <Stack gap="xs">
        <Text fw={500}>{t("dictionaries.usages.title")}</Text>
        <ListTable
          embedded
          list={localListSession({ total: usages.length })}
          columnCount={4}
          minWidth={640}
          emptyMessage={t("dictionaries.usages.empty")}
          head={
            <Table.Tr>
              <Table.Th>{t("entities.fields.tableName")}</Table.Th>
              <Table.Th>{t("entities.fields.attributeName")}</Table.Th>
              <Table.Th>{t("entities.fields.version")}</Table.Th>
              <Table.Th />
            </Table.Tr>
          }
        >
          {usages.map((usage) => (
            <Table.Tr key={`${usage.version_id}:${usage.attribute_name}`}>
              <Table.Td>
                <RecordReference
                  name={usage.entity_name}
                  recordKey={usage.table_name}
                  href={`/console/entities/${usage.entity_id}`}
                />
              </Table.Td>
              <Table.Td>{usage.attribute_name}</Table.Td>
              <Table.Td>{usage.version}</Table.Td>
              <Table.Td>
                {usage.behind ? (
                  <Badge color="orange" variant="light">
                    {t("dictionaries.usages.behind")}
                  </Badge>
                ) : null}
              </Table.Td>
            </Table.Tr>
          ))}
        </ListTable>
      </Stack>
    </Stack>
  );

  return (
    <PageChrome
      title={title}
      recordTitle={recordTitle}
      recent={
        recordTitle
          ? { moduleId: "dictionaries", title: recordTitle }
          : undefined
      }
      titleExtra={
        deprecated ? <DictionaryStatusBadge deprecated /> : undefined
      }
      actions={headerActions}
    >
      {mode === "show" ? (
        body
      ) : (
        <form
          id={DICTIONARY_FORM_ID}
          noValidate
          onSubmit={form.onSubmit((values) => submit(values))}
        >
          <FormErrorSummary failure={saveFailure} />
          {body}
        </form>
      )}
      {recordAction.dialog}
    </PageChrome>
  );
}
