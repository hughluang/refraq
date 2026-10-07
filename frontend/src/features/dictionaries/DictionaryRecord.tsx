"use client";

import { Anchor, Badge, Button, Divider, Group, Stack, Table, Text } from "@mantine/core";
import { useForm } from "@mantine/form";
import { useCan, useNotification, useTranslate } from "@refinedev/core";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState, type ReactNode } from "react";

import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import { EmptyState } from "@/components/feedback/EmptyState";
import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { PageError } from "@/components/feedback/PageError";
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
import { LEAVE_GUARD_ALLOW } from "@/hooks/leaveGuard";
import { useConfirmAction } from "@/hooks/useConfirmAction";
import { useLeaveGuard } from "@/hooks/useLeaveGuard";
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
  const [busy, setBusy] = useState(false);
  const form = useForm<DictionaryFormValues>({
    initialValues: EMPTY_DICTIONARY_FORM,
    validate: (values) => dictionaryFormErrors(values, t),
  });
  const leaveGuard = useLeaveGuard({
    enabled: form.isDirty(),
    message: t("common.leaveUnsaved"),
  });

  const submit = async (values: DictionaryFormValues) => {
    setBusy(true);
    try {
      const description = values.description.trim();
      const created = await createDictionary({
        name: values.name.trim(),
        display_name: values.display_name.trim(),
        ...(description ? { description } : {}),
        entries: entriesFromForm(values.entries),
      });
      form.resetDirty();
      leaveGuard.bypass();
      open?.({ type: "success", message: t("dictionaries.create.success") });
      window.location.replace(
        `/console/dictionaries/${created.dictionary.id}/edit`,
      );
    } catch (err) {
      open?.({
        type: "error",
        message: problemMessage(t, err, String(err)),
      });
    } finally {
      setBusy(false);
    }
  };

  return (
    <PageChrome
      title={t("dictionaries.create.title")}
      actions={
        <Group
          gap="xs"
          wrap="nowrap"
          aria-label={t("dictionaries.actions.standard")}
        >
          <Button
            component={Link}
            href="/console/dictionaries"
            variant="default"
            size="sm"
            data-leave-guard={LEAVE_GUARD_ALLOW}
          >
            {t("common.cancel")}
          </Button>
          <Button type="submit" form={DICTIONARY_FORM_ID} size="sm" loading={busy}>
            {t("dictionaries.create.submit")}
          </Button>
        </Group>
      }
    >
      <form
        id={DICTIONARY_FORM_ID}
        noValidate
        onSubmit={form.onSubmit((values) => void submit(values))}
      >
        <DictionaryFormFields form={form} editable nameEditable />
      </form>
    </PageChrome>
  );
}

function ExistingDictionaryRecord({ mode, dictionaryId }: ExistingProps) {
  const t = useTranslate();
  const router = useRouter();
  const { open } = useNotification();
  const { data: canWrite } = useCan({
    resource: ModuleId.dictionaries,
    action: ModuleAction.edit,
  });
  const [record, setRecord] = useState<Dictionary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const deleteConfirm = useConfirmAction<true>();
  const deprecateConfirm = useConfirmAction<true>();
  const form = useForm<DictionaryFormValues>({
    initialValues: EMPTY_DICTIONARY_FORM,
    validate: (values) => dictionaryFormErrors(values, t),
  });
  const leaveGuard = useLeaveGuard({
    enabled: mode !== "show" && form.isDirty(),
    message: t("common.leaveUnsaved"),
  });

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await getDictionary(dictionaryId);
      setRecord(response.dictionary);
      form.setValues(formFromDictionary(response.dictionary));
      form.resetDirty();
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
    router.replace(`/console/dictionaries/${dictionaryId}`);
  }, [canWrite?.can, dictionaryId, mode, router]);

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
    setBusy(true);
    try {
      const description = values.description.trim();
      await patchDictionary(dictionaryId, {
        display_name: values.display_name.trim(),
        description: description || null,
        entries: entriesFromForm(values.entries),
      });
      form.resetDirty();
      open?.({ type: "success", message: t("dictionaries.update.success") });
      await load();
    } catch (err) {
      notifyError(err, t("dictionaries.update.failed"));
    } finally {
      setBusy(false);
    }
  };

  const confirmDelete = async () => {
    setBusy(true);
    try {
      await deleteDictionary(dictionaryId);
      deleteConfirm.close();
      leaveGuard.bypass();
      open?.({ type: "success", message: t("dictionaries.delete.success") });
      router.replace("/console/dictionaries");
    } catch (err) {
      notifyError(err, t("dictionaries.delete.failed"));
    } finally {
      setBusy(false);
    }
  };

  const confirmDeprecate = async () => {
    setBusy(true);
    try {
      await patchDictionary(dictionaryId, { deprecated: true });
      deprecateConfirm.close();
      open?.({ type: "success", message: t("dictionaries.deprecate.success") });
      await load();
    } catch (err) {
      notifyError(err, t("dictionaries.update.failed"));
    } finally {
      setBusy(false);
    }
  };

  const restore = async () => {
    setBusy(true);
    try {
      await patchDictionary(dictionaryId, { deprecated: false });
      open?.({ type: "success", message: t("dictionaries.restore.success") });
      await load();
    } catch (err) {
      notifyError(err, t("dictionaries.update.failed"));
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <PageChrome title={t("dictionaries.title")}>
        <PageBodySkeleton />
      </PageChrome>
    );
  }

  if (error) {
    return (
      <PageChrome title={t("dictionaries.title")}>
        <PageError message={error} onRetry={() => void load()} />
      </PageChrome>
    );
  }

  if (mode === "edit" && canWrite?.can === false) {
    return (
      <PageChrome title={t("dictionaries.edit.title")}>
        <PageBodySkeleton />
      </PageChrome>
    );
  }

  const title =
    mode === "edit"
      ? t("dictionaries.edit.title")
      : (record?.display_name ?? t("dictionaries.title"));

  const clusters: ReactNode[] = [];
  clusters.push(
    <Group
      key="navigation"
      gap="xs"
      wrap="nowrap"
      aria-label={t("dictionaries.actions.navigation")}
    >
      <Button component={Link} href="/console/dictionaries" variant="default" size="sm">
        {t("dictionaries.backToList")}
      </Button>
      <Button variant="default" size="sm" onClick={() => void load()}>
        {t("jobs.refresh")}
      </Button>
    </Group>,
  );
  if (canWrite?.can) {
    clusters.push(
      <Group
        key="lifecycle"
        gap="xs"
        wrap="nowrap"
        aria-label={t("dictionaries.actions.lifecycle")}
      >
        {deprecated ? (
          <Button
            size="sm"
            variant="light"
            loading={busy}
            disabled={dirty}
            onClick={() => void restore()}
          >
            {t("dictionaries.restore")}
          </Button>
        ) : (
          <Button
            size="sm"
            variant="light"
            color="red"
            loading={busy}
            disabled={dirty}
            onClick={() => deprecateConfirm.open(true)}
          >
            {t("dictionaries.deprecate")}
          </Button>
        )}
      </Group>,
    );
  }
  const showEdit = mode === "show" && Boolean(canWrite?.can);
  const showDelete = !inUse && Boolean(canWrite?.can);
  const showSave = mode !== "show";
  if (showEdit || showDelete || showSave) {
    clusters.push(
      <Group
        key="standard"
        gap="xs"
        wrap="nowrap"
        aria-label={t("dictionaries.actions.standard")}
      >
        {mode === "show" && canWrite?.can ? (
          <Button
            component={Link}
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
            onClick={() => deleteConfirm.open(true)}
          >
            {t("actions.delete")}
          </Button>
        ) : null}
        {showSave ? (
          <Button
            component={Link}
            href={`/console/dictionaries/${dictionaryId}`}
            variant="default"
            size="sm"
            data-leave-guard={LEAVE_GUARD_ALLOW}
          >
            {t("common.cancel")}
          </Button>
        ) : null}
        {showSave ? (
          <Button type="submit" form={DICTIONARY_FORM_ID} size="sm" loading={busy}>
            {t("dictionaries.edit.submit")}
          </Button>
        ) : null}
      </Group>,
    );
  }

  const headerActions = (
    <Group gap="xs" wrap="wrap" align="center">
      {clusters.flatMap((cluster, index) =>
        index === 0
          ? [cluster]
          : [
              <Divider key={`divider-${index}`} orientation="vertical" h={28} />,
              cluster,
            ],
      )}
    </Group>
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
        {usages.length === 0 ? (
          <EmptyState message={t("dictionaries.usages.empty")} />
        ) : (
          <Table horizontalSpacing="sm" verticalSpacing="xs">
            <Table.Thead>
              <Table.Tr>
                <Table.Th>{t("entities.fields.tableName")}</Table.Th>
                <Table.Th>{t("entities.fields.attributeName")}</Table.Th>
                <Table.Th>{t("entities.fields.version")}</Table.Th>
                <Table.Th />
              </Table.Tr>
            </Table.Thead>
            <Table.Tbody>
              {usages.map((usage) => (
                <Table.Tr key={`${usage.version_id}:${usage.attribute_name}`}>
                  <Table.Td>
                    <Anchor
                      component={Link}
                      href={`/console/entities/${usage.entity_id}`}
                      size="sm"
                      ff="monospace"
                    >
                      {usage.table_name}
                    </Anchor>
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
            </Table.Tbody>
          </Table>
        )}
      </Stack>
    </Stack>
  );

  return (
    <PageChrome
      title={title}
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
          onSubmit={form.onSubmit((values) => void submit(values))}
        >
          {body}
        </form>
      )}
      <ConfirmActionModal
        opened={deleteConfirm.opened}
        onClose={deleteConfirm.close}
        title={t("dictionaries.delete.confirmTitle")}
        body={t("dictionaries.delete.confirmBody", {
          name: record?.display_name ?? "",
        })}
        confirmColor="red"
        loading={busy}
        confirmLabel={t("actions.delete")}
        onConfirm={() => void confirmDelete()}
      />
      <ConfirmActionModal
        opened={deprecateConfirm.opened}
        onClose={deprecateConfirm.close}
        title={t("dictionaries.deprecate.confirmTitle")}
        body={t("dictionaries.deprecate.confirmBody", {
          name: record?.display_name ?? "",
        })}
        confirmColor="red"
        loading={busy}
        confirmLabel={t("dictionaries.deprecate")}
        onConfirm={() => void confirmDeprecate()}
      />
    </PageChrome>
  );
}
