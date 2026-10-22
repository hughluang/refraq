"use client";

import { Button, Group, Stack, Text } from "@mantine/core";
import { useCan, useNotification, useTranslate } from "@refinedev/core";
import { useCallback, useEffect, useState } from "react";

import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import {
  FormErrorSummary,
  saveFailureFrom,
  type SaveFailure,
} from "@/components/form/FormErrorSummary";
import { NumberField } from "@/components/form/NumberField";
import { SelectField } from "@/components/form/SelectField";
import { SwitchField } from "@/components/form/SwitchField";
import { TextField } from "@/components/form/TextField";
import { useConsoleForm } from "@/components/form/useConsoleForm";
import { HeaderAction, HeaderActions } from "@/components/layout/HeaderActions";
import { PageChrome } from "@/components/layout/PageChrome";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { suppressLeaveGuard } from "@/components/navigation/leaveGuard";
import { useConsoleNavigation } from "@/components/navigation/useConsoleNavigation";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import {
  createEmailAccount,
  deleteEmailAccount,
  getEmailAccount,
  patchEmailAccount,
  testEmailAccount,
} from "@/features/email-accounts/api";
import type {
  EmailAccount,
  EmailAccountTestResult,
  EmailEncryption,
} from "@/features/email-accounts/types";
import { ApiError } from "@/lib/api";
import { problemMessage } from "@/lib/problem";

const FORM_ID = "email-account-record-form";

type Values = {
  name: string;
  host: string;
  port: number | "";
  encryption: EmailEncryption;
  username: string;
  password: string;
  clearPassword: boolean;
  from: string;
  tlsSkipVerify: boolean;
};

type Props = { mode: "create" } | { mode: "show" | "edit"; accountId: string };

const EMPTY: Values = {
  name: "",
  host: "",
  port: 587,
  encryption: "starttls",
  username: "",
  password: "",
  clearPassword: false,
  from: "",
  tlsSkipVerify: false,
};

export function EmailAccountRecord(props: Props) {
  if (props.mode === "create") return <EmailAccountCreate />;
  return <EmailAccountExisting mode={props.mode} accountId={props.accountId} />;
}

function EmailAccountCreate() {
  const t = useTranslate();
  const { open } = useNotification();
  const [saveFailure, setSaveFailure] = useState<SaveFailure | null>(null);
  const form = useConsoleForm<Values>({
    initialValues: EMPTY,
    onValuesChange: () => setSaveFailure(null),
    validate: (values) => validateAccount(values, t),
  });
  return (
    <PageChrome
      title={t("emailAccounts.createTitle")}
      actions={
        <HeaderActions
          standard={
            <>
              <Button
                component={ConsoleLink}
                href="/console/email-accounts"
                variant="default"
                size="sm"
              >
                {t("common.cancel")}
              </Button>
              <HeaderAction primary>
                <Button type="submit" form={FORM_ID} size="sm" loading={form.submitting}>
                  {t("emailAccounts.createSubmit")}
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
          const port = Number(values.port);
          void createEmailAccount({
            name: values.name.trim(),
            host: values.host.trim(),
            port,
            encryption: values.encryption,
            username: values.username.trim() || null,
            password: values.password || null,
            from: values.from.trim(),
            tls_skip_verify: values.tlsSkipVerify,
          })
            .then((created) => {
              form.markSaved();
              suppressLeaveGuard();
              open?.({ type: "success", message: t("emailAccounts.created") });
              window.location.replace(`/console/email-accounts/${created.email_account.id}/edit`);
            })
            .catch((error: unknown) => {
              setSaveFailure(saveFailureFrom(t, error, form.applyApiError(error), String(error)));
            });
        })}
      >
        <Stack gap="sm">
          <FormErrorSummary failure={saveFailure} />
          <AccountFields form={form} editable passwordMode="create" />
        </Stack>
      </form>
    </PageChrome>
  );
}

function EmailAccountExisting({
  mode,
  accountId,
}: {
  mode: "show" | "edit";
  accountId: string;
}) {
  const t = useTranslate();
  const { replace } = useConsoleNavigation();
  const { open } = useNotification();
  const { data: canWrite } = useCan({
    resource: ModuleId.emailAccounts,
    action: ModuleAction.edit,
  });
  const [record, setRecord] = useState<EmailAccount | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [saveFailure, setSaveFailure] = useState<SaveFailure | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testTo, setTestTo] = useState("");
  const [testResult, setTestResult] = useState<EmailAccountTestResult | null>(null);
  const form = useConsoleForm<Values>({
    initialValues: EMPTY,
    onValuesChange: () => setSaveFailure(null),
    validate: (values) => validateAccount(values, t),
  });
  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    void getEmailAccount(accountId)
      .then((body) => {
        setRecord(body.email_account);
        form.setValues({
          name: body.email_account.name,
          host: body.email_account.host,
          port: body.email_account.port,
          encryption: body.email_account.encryption,
          username: body.email_account.username ?? "",
          password: "",
          clearPassword: false,
          from: body.email_account.from,
          tlsSkipVerify: body.email_account.tls_skip_verify,
        });
        form.markSaved();
      })
      .catch((err: unknown) => setError(err))
      .finally(() => setLoading(false));
  }, [accountId]);
  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    if (mode === "edit" && canWrite?.can === false) replace(`/console/email-accounts/${accountId}`);
  }, [canWrite?.can, mode, replace, accountId]);
  if (loading || !record) {
    return (
      <PageChrome
        title={t("emailAccounts.title")}
        status={error ? "error" : "loading"}
        errorMessage={error ? problemMessage(t, error, t("emailAccounts.loadFailed")) : undefined}
        requestId={error instanceof ApiError ? error.requestId : null}
        onRetry={load}
      />
    );
  }
  const editable = mode === "edit" && Boolean(canWrite?.can);
  return (
    <PageChrome
      title={t("emailAccounts.title")}
      recordTitle={record.name}
      recent={{ moduleId: "email-accounts", title: record.name }}
      actions={
        <HeaderActions
          standard={
            <Group gap="xs">
              {mode === "show" && canWrite?.can ? (
                <Button
                  component={ConsoleLink}
                  href={`/console/email-accounts/${accountId}/edit`}
                  size="sm"
                  variant="light"
                >
                  {t("emailAccounts.edit")}
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
                  {t("emailAccounts.delete")}
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
                  const to = testTo.trim();
                  if (!to) {
                    open?.({ type: "error", message: t("emailAccounts.validation.testTo") });
                    return;
                  }
                  setTesting(true);
                  void testEmailAccount(accountId, to)
                    .then((result) => {
                      setTestResult(result);
                      setRecord(result.email_account);
                    })
                    .catch((err: unknown) => {
                      presentProblemNotification(t, err);
                    })
                    .finally(() => setTesting(false));
                }}
              >
                {t("emailAccounts.test")}
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
          const body: {
            name: string;
            host: string;
            port: number;
            encryption: EmailEncryption;
            username: string | null;
            from: string;
            tls_skip_verify: boolean;
            password?: string | null;
          } = {
            name: values.name.trim(),
            host: values.host.trim(),
            port: Number(values.port),
            encryption: values.encryption,
            username: values.username.trim() || null,
            from: values.from.trim(),
            tls_skip_verify: values.tlsSkipVerify,
          };
          if (values.clearPassword) body.password = null;
          else if (values.password) body.password = values.password;
          void patchEmailAccount(accountId, body)
            .then((saved) => {
              setRecord(saved.email_account);
              form.setValues({ ...values, password: "", clearPassword: false });
              form.markSaved();
              open?.({ type: "success", message: t("emailAccounts.saved") });
            })
            .catch((err: unknown) => {
              setSaveFailure(saveFailureFrom(t, err, form.applyApiError(err), String(err)));
            });
        })}
      >
        <Stack gap="sm">
          <FormErrorSummary failure={saveFailure} />
          <AccountFields
            form={form}
            editable={editable}
            passwordMode={record.password_set ? "replace" : "create"}
          />
        </Stack>
      </form>
      {canWrite?.can ? (
        <Stack gap="sm" mt="md">
          <TextField
            editable
            label={t("emailAccounts.fields.testTo")}
            description={t("emailAccounts.fields.testToHint")}
            value={testTo}
            onChange={(event) => setTestTo(event.currentTarget.value)}
          />
          {testResult ? (
            <Text size="sm">
              {testResult.ok
                ? t("emailAccounts.testOk")
                : t("emailAccounts.testError", { error: testResult.error ?? "" })}
            </Text>
          ) : null}
        </Stack>
      ) : null}
      <ConfirmActionModal
        opened={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        title={t("emailAccounts.deleteTitle")}
        confirmLabel={t("emailAccounts.delete")}
        confirmColor="red"
        loading={deleting}
        onConfirm={() => {
          setDeleting(true);
          void deleteEmailAccount(accountId)
            .then(() => {
              suppressLeaveGuard();
              window.location.assign("/console/email-accounts");
            })
            .catch((err: unknown) => {
              setDeleting(false);
              setConfirmDelete(false);
              presentProblemNotification(t, err);
            });
        }}
      />
    </PageChrome>
  );
}

function AccountFields({
  form,
  editable,
  passwordMode,
}: {
  form: ReturnType<typeof useConsoleForm<Values>>;
  editable: boolean;
  passwordMode: "create" | "replace";
}) {
  const t = useTranslate();
  const encryption = [
    { value: "none", label: t("emailAccounts.encryption.none") },
    { value: "starttls", label: t("emailAccounts.encryption.starttls") },
    { value: "implicit_tls", label: t("emailAccounts.encryption.implicitTls") },
  ];
  return (
    <Stack gap="sm">
      <TextField editable={editable} label={t("emailAccounts.fields.name")} {...form.fieldProps("name")} />
      <TextField
        editable={editable}
        label={t("emailAccounts.fields.host")}
        description={t("emailAccounts.fields.hostHint")}
        {...form.fieldProps("host")}
      />
      <NumberField
        editable={editable}
        label={t("emailAccounts.fields.port")}
        min={1}
        max={65535}
        {...form.fieldProps("port")}
      />
      <SelectField
        editable={editable}
        label={t("emailAccounts.fields.encryption")}
        data={encryption}
        {...form.fieldProps("encryption")}
      />
      <TextField
        editable={editable}
        label={t("emailAccounts.fields.username")}
        description={t("emailAccounts.fields.usernameHint")}
        {...form.fieldProps("username")}
      />
      {editable ? (
        <TextField
          editable
          type="password"
          label={t("emailAccounts.fields.password")}
          description={
            passwordMode === "replace"
              ? t("emailAccounts.fields.passwordKeep")
              : t("emailAccounts.fields.passwordHint")
          }
          {...form.fieldProps("password")}
        />
      ) : (
        <Text size="sm">
          {passwordMode === "replace"
            ? t("emailAccounts.fields.passwordSet")
            : t("emailAccounts.fields.passwordEmpty")}
        </Text>
      )}
      {editable && passwordMode === "replace" ? (
        <SwitchField
          editable
          label={t("emailAccounts.fields.clearPassword")}
          {...form.fieldProps("clearPassword", { type: "checkbox" })}
        />
      ) : null}
      <TextField
        editable={editable}
        label={t("emailAccounts.fields.from")}
        description={t("emailAccounts.fields.fromHint")}
        {...form.fieldProps("from")}
      />
      <SwitchField
        editable={editable}
        label={t("emailAccounts.fields.tlsSkipVerify")}
        description={t("emailAccounts.fields.tlsSkipVerifyHint")}
        {...form.fieldProps("tlsSkipVerify", { type: "checkbox" })}
      />
    </Stack>
  );
}

function validateAccount(
  values: Values,
  t: (key: string) => string,
): Partial<Record<keyof Values, string>> {
  const errors: Partial<Record<keyof Values, string>> = {};
  const port = Number(values.port);
  if (!values.name.trim()) errors.name = t("emailAccounts.validation.name");
  if (!values.host.trim()) errors.host = t("emailAccounts.validation.host");
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    errors.port = t("emailAccounts.validation.port");
  }
  if (!values.from.trim()) errors.from = t("emailAccounts.validation.from");
  return errors;
}
