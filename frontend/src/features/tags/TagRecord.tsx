"use client";

import { Button, Group, Stack } from "@mantine/core";
import { useCan, useNotification, useTranslate } from "@refinedev/core";
import { useCallback, useEffect, useState } from "react";

import { DisplayField } from "@/components/display/DisplayField";
import { useConsoleMutation } from "@/components/feedback/useConsoleMutation";
import {
  FormErrorSummary,
  saveFailureFrom,
  type SaveFailure,
} from "@/components/form/FormErrorSummary";
import { useConsoleForm } from "@/components/form/useConsoleForm";
import { HeaderAction, HeaderActions } from "@/components/layout/HeaderActions";
import { PageChrome } from "@/components/layout/PageChrome";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { suppressLeaveGuard } from "@/components/navigation/leaveGuard";
import { useConsoleNavigation } from "@/components/navigation/useConsoleNavigation";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import { createTag, deleteTag, getTag, patchTag } from "@/features/tags/api";
import { TagFormFields } from "@/features/tags/TagFormFields";
import { TagUsage } from "@/features/tags/TagUsage";
import {
  EMPTY_TAG_FORM,
  formFromTag,
  tagFormErrors,
} from "@/features/tags/tagForm";
import type { Tag, TagFormValues } from "@/features/tags/types";
import { problemMessage } from "@/lib/problem";

const TAG_FORM_ID = "tag-record-form";

type TagLoad =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; tag: Tag };

type Props = { mode: "create" } | { mode: "show" | "edit"; tagId: string };

export function TagRecord(props: Props) {
  if (props.mode === "create") return <TagCreateForm />;
  return <ExistingTagRecord mode={props.mode} tagId={props.tagId} />;
}

function TagCreateForm() {
  const t = useTranslate();
  const { open } = useNotification();
  const [saveFailure, setSaveFailure] = useState<SaveFailure | null>(null);
  const form = useConsoleForm<TagFormValues>({
    initialValues: EMPTY_TAG_FORM,
    onValuesChange: () => setSaveFailure(null),
    validate: (values) => tagFormErrors(values, t),
  });

  const submit = async (values: TagFormValues) => {
    try {
      const created = await createTag({
        name: values.name,
        description: values.description,
      });
      form.markSaved();
      suppressLeaveGuard();
      open?.({ type: "success", message: t("tags.create.success") });
      window.location.replace(`/console/tags/${created.tag.id}/edit`);
    } catch (error) {
      setSaveFailure(
        saveFailureFrom(t, error, form.applyApiError(error), String(error)),
      );
    }
  };

  return (
    <PageChrome
      title={t("tags.create.title")}
      actions={
        <HeaderActions
          standard={
            <>
              <Button
                component={ConsoleLink}
                href="/console/tags"
                variant="default"
                size="sm"
              >
                {t("common.cancel")}
              </Button>
              <HeaderAction primary>
                <Button
                  type="submit"
                  form={TAG_FORM_ID}
                  size="sm"
                  loading={form.submitting}
                >
                  {t("tags.create.submit")}
                </Button>
              </HeaderAction>
            </>
          }
        />
      }
    >
      <form
        id={TAG_FORM_ID}
        noValidate
        onSubmit={form.onSubmit((values) => submit(values))}
      >
        <Stack gap="sm">
          <FormErrorSummary failure={saveFailure} />
          <TagFormFields form={form} editable />
        </Stack>
      </form>
    </PageChrome>
  );
}

function ExistingTagRecord({
  mode,
  tagId,
}: {
  mode: "show" | "edit";
  tagId: string;
}) {
  const t = useTranslate();
  const { replace } = useConsoleNavigation();
  const { open } = useNotification();
  const { data: canWrite } = useCan({
    resource: ModuleId.tags,
    action: ModuleAction.edit,
  });
  const [loaded, setLoaded] = useState<TagLoad>({ status: "loading" });
  const recordAction = useConsoleMutation();
  const [saveFailure, setSaveFailure] = useState<SaveFailure | null>(null);
  const form = useConsoleForm<TagFormValues>({
    initialValues: EMPTY_TAG_FORM,
    onValuesChange: () => setSaveFailure(null),
    validate: (values) => tagFormErrors(values, t),
  });

  const load = useCallback(async () => {
    setLoaded({ status: "loading" });
    try {
      const response = await getTag(tagId);
      setLoaded({ status: "ready", tag: response.tag });
      form.setValues(formFromTag(response.tag));
      form.markSaved();
    } catch (err) {
      setLoaded({
        status: "error",
        message: problemMessage(t, err, String(err)),
      });
    }
  }, [tagId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (mode !== "edit") return;
    if (canWrite?.can !== false) return;
    suppressLeaveGuard();
    replace(`/console/tags/${tagId}`);
  }, [canWrite?.can, mode, replace, tagId]);

  const submit = async (values: TagFormValues) => {
    try {
      await patchTag(tagId, {
        name: values.name,
        description: values.description,
      });
      form.markSaved();
      setSaveFailure(null);
      open?.({ type: "success", message: t("tags.update.success") });
      await load();
    } catch (err) {
      setSaveFailure(
        saveFailureFrom(
          t,
          err,
          form.applyApiError(err),
          t("tags.update.failed"),
        ),
      );
    }
  };

  if (loaded.status === "loading") {
    return <PageChrome title={t("tags.title")} status="loading" />;
  }

  if (loaded.status === "error") {
    return (
      <PageChrome
        title={t("tags.title")}
        status="error"
        errorMessage={loaded.message}
        onRetry={() => void load()}
      />
    );
  }

  const record = loaded.tag;

  function onDelete() {
    recordAction.run({
      safety: "confirm",
      key: "delete",
      recordName: record.name,
      title: t("tags.delete.confirmTitle"),
      consequence: t("tags.delete.consequence"),
      confirmLabel: t("actions.delete"),
      confirmColor: "red",
      outcome: t("tags.delete.success"),
      execute: async () => {
        await deleteTag(tagId);
        suppressLeaveGuard();
        replace("/console/tags");
      },
    });
  }

  if (mode === "edit" && canWrite?.can === false) {
    return <PageChrome title={t("tags.edit.title")} status="loading" />;
  }

  const fieldsWritable = mode === "edit" && Boolean(canWrite?.can);
  const showEdit = mode === "show" && Boolean(canWrite?.can);
  const showDelete = Boolean(canWrite?.can);
  const showSave = mode !== "show";
  const recordTitle = record.name;

  const navigationActions = (
    <Group gap="xs" wrap="nowrap" aria-label={t("tags.actions.navigation")}>
      <Button component={ConsoleLink} href="/console/tags" variant="default" size="sm">
        {t("tags.backToList")}
      </Button>
      <Button variant="default" size="sm" onClick={() => void load()}>
        {t("jobs.refresh")}
      </Button>
    </Group>
  );
  const standardActions =
    showEdit || showDelete || showSave ? (
      <Group gap="xs" wrap="nowrap" aria-label={t("tags.actions.standard")}>
        {showEdit ? (
          <Button
            component={ConsoleLink}
            href={`/console/tags/${tagId}/edit`}
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
            href={`/console/tags/${tagId}`}
            variant="default"
            size="sm"
          >
            {t("common.cancel")}
          </Button>
        ) : null}
        {showSave ? (
          <HeaderAction primary>
            <Button type="submit" form={TAG_FORM_ID} size="sm" loading={form.submitting}>
              {t("tags.edit.submit")}
            </Button>
          </HeaderAction>
        ) : null}
      </Group>
    ) : null;

  const body = (
    <Stack>
      <TagFormFields form={form} editable={fieldsWritable} />
      <DisplayField label={t("tags.fields.entityCount")} value={record.entity_count} />
      <DisplayField label={t("tags.fields.channelCount")} value={record.channel_count} />
    </Stack>
  );

  return (
    <PageChrome
      title={t("tags.title")}
      recordTitle={recordTitle}
      recent={{ moduleId: "tags", title: recordTitle }}
      actions={
        <HeaderActions navigation={navigationActions} standard={standardActions} />
      }
    >
      {mode === "show" ? (
        <Stack>
          {body}
          <TagUsage tagId={tagId} />
        </Stack>
      ) : (
        <form
          id={TAG_FORM_ID}
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
