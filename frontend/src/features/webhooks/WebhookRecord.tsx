"use client";

import { Button, Group, Stack, Switch, Text } from "@mantine/core";
import { useCan, useNotification, useTranslate } from "@refinedev/core";
import { useCallback, useEffect, useState } from "react";

import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import {
  FormErrorSummary,
  saveFailureFrom,
  type SaveFailure,
} from "@/components/form/FormErrorSummary";
import { TextField } from "@/components/form/TextField";
import { useConsoleForm } from "@/components/form/useConsoleForm";
import { HeaderAction, HeaderActions } from "@/components/layout/HeaderActions";
import { PageChrome } from "@/components/layout/PageChrome";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { suppressLeaveGuard } from "@/components/navigation/leaveGuard";
import { useConsoleNavigation } from "@/components/navigation/useConsoleNavigation";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import {
  createWebhook,
  deleteWebhook,
  getWebhook,
  patchWebhook,
  testWebhook,
} from "@/features/webhooks/api";
import type { Webhook, WebhookTestResult } from "@/features/webhooks/types";
import { problemMessage } from "@/lib/problem";

const FORM_ID = "webhook-record-form";

type Values = {
  name: string;
  url: string;
  secret: string;
  clearSecret: boolean;
};

type Props = { mode: "create" } | { mode: "show" | "edit"; webhookId: string };

export function WebhookRecord(props: Props) {
  if (props.mode === "create") return <WebhookCreate />;
  return <WebhookExisting mode={props.mode} webhookId={props.webhookId} />;
}

function WebhookCreate() {
  const t = useTranslate();
  const { open } = useNotification();
  const [saveFailure, setSaveFailure] = useState<SaveFailure | null>(null);
  const form = useConsoleForm<Values>({
    initialValues: { name: "", url: "", secret: "", clearSecret: false },
    onValuesChange: () => setSaveFailure(null),
    validate: (values) => validateWebhook(values, t),
  });
  return (
    <PageChrome
      title={t("webhooks.createTitle")}
      actions={
        <HeaderActions
          standard={
            <>
              <Button component={ConsoleLink} href="/console/webhooks" variant="default" size="sm">
                {t("common.cancel")}
              </Button>
              <HeaderAction primary>
                <Button type="submit" form={FORM_ID} size="sm" loading={form.submitting}>
                  {t("webhooks.createSubmit")}
                </Button>
              </HeaderAction>
            </>
          }
        />
      }
    >
      <form
        id={FORM_ID}
        noValidate
        onSubmit={form.onSubmit((values) => {
          void createWebhook({
            name: values.name.trim(),
            url: values.url.trim(),
            secret: values.secret.trim() || null,
          })
            .then((created) => {
              form.markSaved();
              suppressLeaveGuard();
              open?.({ type: "success", message: t("webhooks.created") });
              window.location.replace(`/console/webhooks/${created.webhook.id}/edit`);
            })
            .catch((error: unknown) => {
              setSaveFailure(saveFailureFrom(t, error, form.applyApiError(error), String(error)));
            });
        })}
      >
        <Stack gap="sm">
          <FormErrorSummary failure={saveFailure} />
          <WebhookFields form={form} editable secretMode="create" />
        </Stack>
      </form>
    </PageChrome>
  );
}

function WebhookExisting({
  mode,
  webhookId,
}: {
  mode: "show" | "edit";
  webhookId: string;
}) {
  const t = useTranslate();
  const { replace } = useConsoleNavigation();
  const { open } = useNotification();
  const { data: canWrite } = useCan({
    resource: ModuleId.webhooks,
    action: ModuleAction.edit,
  });
  const [record, setRecord] = useState<Webhook | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [saveFailure, setSaveFailure] = useState<SaveFailure | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<WebhookTestResult | null>(null);
  const form = useConsoleForm<Values>({
    initialValues: { name: "", url: "", secret: "", clearSecret: false },
    onValuesChange: () => setSaveFailure(null),
    validate: (values) => validateWebhook(values, t),
  });
  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    void getWebhook(webhookId)
      .then((body) => {
        setRecord(body.webhook);
        form.setValues({
          name: body.webhook.name,
          url: body.webhook.url,
          secret: "",
          clearSecret: false,
        });
        form.markSaved();
      })
      .catch((err: unknown) => setError(err))
      .finally(() => setLoading(false));
  }, [webhookId]);
  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    if (mode === "edit" && canWrite?.can === false) replace(`/console/webhooks/${webhookId}`);
  }, [canWrite?.can, mode, replace, webhookId]);
  if (loading || !record) {
    return (
      <PageChrome
        title={t("webhooks.title")}
        status={error ? "error" : "loading"}
        errorMessage={error ? problemMessage(t, error, t("webhooks.loadFailed")) : undefined}
        onRetry={load}
      />
    );
  }
  const editable = mode === "edit" && Boolean(canWrite?.can);
  return (
    <PageChrome
      title={t("webhooks.title")}
      recordTitle={record.name}
      recent={{ moduleId: "webhooks", title: record.name }}
      actions={
        <HeaderActions
          standard={
            <Group gap="xs">
              {mode === "show" && canWrite?.can ? (
                <Button
                  component={ConsoleLink}
                  href={`/console/webhooks/${webhookId}/edit`}
                  size="sm"
                  variant="light"
                >
                  {t("webhooks.edit")}
                </Button>
              ) : null}
              {editable ? (
                <HeaderAction primary>
                  <Button type="submit" form={FORM_ID} size="sm" loading={form.submitting}>
                    {t("common.save")}
                  </Button>
                </HeaderAction>
              ) : null}
              {canWrite?.can ? (
                <Button size="sm" variant="light" color="red" onClick={() => setConfirmDelete(true)}>
                  {t("webhooks.delete")}
                </Button>
              ) : null}
            </Group>
          }
          lifecycle={
            canWrite?.can ? (
              <Button
                size="sm"
                variant="default"
                loading={testing}
                onClick={() => {
                  setTesting(true);
                  void testWebhook(webhookId)
                    .then((result) => {
                      setTestResult(result);
                      setRecord(result.webhook);
                    })
                    .catch((err: unknown) => {
                      open?.({
                        type: "error",
                        message: problemMessage(t, err, t("webhooks.testFailed")),
                      });
                    })
                    .finally(() => setTesting(false));
                }}
              >
                {t("webhooks.test")}
              </Button>
            ) : null
          }
        />
      }
    >
      <form
        id={FORM_ID}
        noValidate
        onSubmit={form.onSubmit((values) => {
          const body: { name: string; url: string; secret?: string | null } = {
            name: values.name.trim(),
            url: values.url.trim(),
          };
          if (values.clearSecret) body.secret = null;
          else if (values.secret.trim()) body.secret = values.secret.trim();
          void patchWebhook(webhookId, body)
            .then((saved) => {
              setRecord(saved.webhook);
              form.setValues({ ...values, secret: "", clearSecret: false });
              form.markSaved();
              open?.({ type: "success", message: t("webhooks.saved") });
            })
            .catch((err: unknown) => {
              setSaveFailure(saveFailureFrom(t, err, form.applyApiError(err), String(err)));
            });
        })}
      >
        <Stack gap="sm">
          <FormErrorSummary failure={saveFailure} />
          <WebhookFields
            form={form}
            editable={editable}
            secretMode={record.secret_set ? "replace" : "create"}
          />
          {testResult ? (
            <Text size="sm">
              {testResult.ok
                ? t("webhooks.testOk", { status: String(testResult.status_code ?? "") })
                : t("webhooks.testError", { error: testResult.error ?? "" })}
            </Text>
          ) : null}
        </Stack>
      </form>
      <ConfirmActionModal
        opened={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        title={t("webhooks.deleteTitle")}
        confirmLabel={t("webhooks.delete")}
        confirmColor="red"
        loading={deleting}
        onConfirm={() => {
          setDeleting(true);
          void deleteWebhook(webhookId)
            .then(() => {
              suppressLeaveGuard();
              window.location.assign("/console/webhooks");
            })
            .catch((err: unknown) => {
              setDeleting(false);
              setConfirmDelete(false);
              open?.({
                type: "error",
                message: problemMessage(t, err, t("webhooks.deleteFailed")),
              });
            });
        }}
      />
    </PageChrome>
  );
}

function WebhookFields({
  form,
  editable,
  secretMode,
}: {
  form: ReturnType<typeof useConsoleForm<Values>>;
  editable: boolean;
  secretMode: "create" | "replace";
}) {
  const t = useTranslate();
  return (
    <Stack gap="sm">
      <TextField
        editable={editable}
        label={t("webhooks.fields.name")}
        {...form.fieldProps("name")}
      />
      <TextField
        editable={editable}
        label={t("webhooks.fields.url")}
        description={t("webhooks.fields.urlHint")}
        {...form.fieldProps("url")}
      />
      {editable ? (
        <TextField
          editable
          type="password"
          label={t("webhooks.fields.secret")}
          description={
            secretMode === "replace"
              ? t("webhooks.fields.secretKeep")
              : t("webhooks.fields.secretHint")
          }
          {...form.fieldProps("secret")}
        />
      ) : (
        <Text size="sm">
          {secretMode === "replace" ? t("webhooks.fields.secretSet") : t("webhooks.fields.secretEmpty")}
        </Text>
      )}
      {editable && secretMode === "replace" ? (
        <Switch
          label={t("webhooks.fields.clearSecret")}
          checked={form.values.clearSecret}
          onChange={(event) => form.setFieldValue("clearSecret", event.currentTarget.checked)}
        />
      ) : null}
    </Stack>
  );
}

function validateWebhook(
  values: Values,
  t: (key: string) => string,
): Partial<Record<keyof Values, string>> {
  const errors: Partial<Record<keyof Values, string>> = {};
  if (!values.name.trim()) errors.name = t("webhooks.validation.name");
  if (!values.url.trim()) errors.url = t("webhooks.validation.url");
  return errors;
}
