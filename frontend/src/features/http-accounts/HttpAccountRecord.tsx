"use client";

import { Button, Group, Stack, Text } from "@mantine/core";
import { useCan, useNotification, useTranslate } from "@refinedev/core";
import { useCallback, useEffect, useRef, useState } from "react";

import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import {
  FormErrorSummary,
  saveFailureFrom,
  type SaveFailure,
} from "@/components/form/FormErrorSummary";
import { SelectField } from "@/components/form/SelectField";
import { TextField } from "@/components/form/TextField";
import { useConsoleForm } from "@/components/form/useConsoleForm";
import { HeaderAction, HeaderActions } from "@/components/layout/HeaderActions";
import { PageChrome } from "@/components/layout/PageChrome";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { suppressLeaveGuard } from "@/components/navigation/leaveGuard";
import { useConsoleNavigation } from "@/components/navigation/useConsoleNavigation";
import { ModuleAction, ModuleId } from "@/features/console/module-identity";
import {
  createHttpAccount,
  deleteHttpAccount,
  getHttpAccount,
  patchHttpAccount,
} from "@/features/http-accounts/api";
import type {
  HttpAccount,
  HttpAccountWrite,
  HttpAuthType,
} from "@/features/http-accounts/types";
import { ApiError } from "@/lib/api";
import { problemMessage } from "@/lib/problem";

const FORM_ID = "http-account-record-form";

type Pair = { name: string; value: string };

type Values = {
  name: string;
  authType: HttpAuthType;
  username: string;
  secret: string;
  headers: Pair[];
  query: Pair[];
  origins: string[];
};

type Baseline = {
  authType: HttpAuthType;
  username: string;
  headers: Pair[];
  query: Pair[];
};

type Props = { mode: "create" } | { mode: "show" | "edit"; accountId: string };

const EMPTY: Values = {
  name: "",
  authType: "none",
  username: "",
  secret: "",
  headers: [],
  query: [],
  origins: [],
};

export function HttpAccountRecord(props: Props) {
  if (props.mode === "create") return <HttpAccountCreate />;
  return <HttpAccountExisting mode={props.mode} accountId={props.accountId} />;
}

function HttpAccountCreate() {
  const t = useTranslate();
  const { open } = useNotification();
  const baseline = useRef<Baseline | null>(null);
  const [saveFailure, setSaveFailure] = useState<SaveFailure | null>(null);
  const form = useConsoleForm<Values>({
    initialValues: EMPTY,
    onValuesChange: () => setSaveFailure(null),
    validate: (values) => validateAccount(values, t, baseline.current),
  });
  return (
    <PageChrome
      title={t("httpAccounts.createTitle")}
      actions={
        <HeaderActions
          standard={
            <>
              <Button
                component={ConsoleLink}
                href="/console/http-accounts"
                variant="default"
                size="sm"
              >
                {t("common.cancel")}
              </Button>
              <HeaderAction primary>
                <Button type="submit" form={FORM_ID} size="sm" loading={form.submitting}>
                  {t("httpAccounts.createSubmit")}
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
          void createHttpAccount(writeBody(values, null))
            .then((created) => {
              form.markSaved();
              suppressLeaveGuard();
              open?.({ type: "success", message: t("httpAccounts.created") });
              window.location.replace(`/console/http-accounts/${created.http_account.id}/edit`);
            })
            .catch((error: unknown) => {
              setSaveFailure(saveFailureFrom(t, error, form.applyApiError(error), String(error)));
            });
        })}
      >
        <Stack gap="sm">
          <FormErrorSummary failure={saveFailure} />
          <AccountFields form={form} editable secretState="empty" mode="create" />
        </Stack>
      </form>
    </PageChrome>
  );
}

function HttpAccountExisting({
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
    resource: ModuleId.httpAccounts,
    action: ModuleAction.edit,
  });
  const baseline = useRef<Baseline | null>(null);
  const [record, setRecord] = useState<HttpAccount | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [saveFailure, setSaveFailure] = useState<SaveFailure | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const form = useConsoleForm<Values>({
    initialValues: EMPTY,
    onValuesChange: () => setSaveFailure(null),
    validate: (values) => validateAccount(values, t, baseline.current),
  });
  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    void getHttpAccount(accountId)
      .then((body) => {
        const account = body.http_account;
        baseline.current = baselineFrom(account);
        form.setValues(valuesFrom(account));
        form.markSaved();
        setRecord(account);
      })
      .catch((err: unknown) => setError(err))
      .finally(() => setLoading(false));
  }, [accountId]);
  useEffect(() => {
    load();
  }, [load]);
  useEffect(() => {
    if (mode === "edit" && canWrite?.can === false) replace(`/console/http-accounts/${accountId}`);
  }, [canWrite?.can, mode, replace, accountId]);
  if (loading || !record) {
    return (
      <PageChrome
        title={t("httpAccounts.title")}
        status={error ? "error" : "loading"}
        errorMessage={error ? problemMessage(t, error, t("httpAccounts.loadFailed")) : undefined}
        requestId={error instanceof ApiError ? error.requestId : null}
        onRetry={load}
      />
    );
  }
  const editable = mode === "edit" && Boolean(canWrite?.can);
  const secretState = secretStateOf(record);
  return (
    <PageChrome
      title={t("httpAccounts.title")}
      recordTitle={record.name}
      recent={{ moduleId: "http-accounts", title: record.name }}
      actions={
        <HeaderActions
          standard={
            <Group gap="xs">
              {mode === "show" && canWrite?.can ? (
                <Button
                  component={ConsoleLink}
                  href={`/console/http-accounts/${accountId}/edit`}
                  size="sm"
                  variant="light"
                >
                  {t("httpAccounts.edit")}
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
                  {t("httpAccounts.delete")}
                </Button>
              ) : null}
            </Group>
          }
        />
      }
    >
      <form
        id={FORM_ID}
        noValidate
        onSubmit={form.onSubmit((values) => {
          void patchHttpAccount(accountId, writeBody(values, baseline.current))
            .then((saved) => {
              const account = saved.http_account;
              baseline.current = baselineFrom(account);
              form.setValues(valuesFrom(account));
              form.markSaved();
              setRecord(account);
              open?.({ type: "success", message: t("httpAccounts.saved") });
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
            secretState={secretState}
            mode={mode}
            baseline={baseline.current}
            headerNames={record.headers.map((item) => item.name)}
            queryNames={record.query.map((item) => item.name)}
          />
        </Stack>
      </form>
      <ConfirmActionModal
        opened={confirmDelete}
        onClose={() => setConfirmDelete(false)}
        title={t("httpAccounts.deleteTitle")}
        confirmLabel={t("httpAccounts.delete")}
        confirmColor="red"
        loading={deleting}
        onConfirm={() => {
          setDeleting(true);
          void deleteHttpAccount(accountId)
            .then(() => {
              suppressLeaveGuard();
              window.location.assign("/console/http-accounts");
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
  secretState,
  mode,
  baseline = null,
  headerNames = [],
  queryNames = [],
}: {
  form: ReturnType<typeof useConsoleForm<Values>>;
  editable: boolean;
  secretState: "token" | "password" | "empty";
  mode: "create" | "show" | "edit";
  baseline?: Baseline | null;
  headerNames?: string[];
  queryNames?: string[];
}) {
  const t = useTranslate();
  const authType = form.values.authType;
  const authOptions = [
    { value: "none", label: t("httpAccounts.auth.none") },
    { value: "bearer", label: t("httpAccounts.auth.bearer") },
    { value: "basic", label: t("httpAccounts.auth.basic") },
  ];
  return (
    <Stack gap="sm">
      <TextField
        editable={editable}
        label={t("httpAccounts.fields.name")}
        {...form.fieldProps("name")}
      />
      <SelectField
        editable={editable}
        label={t("httpAccounts.fields.auth")}
        data={authOptions}
        {...form.fieldProps("authType")}
      />
      {authType === "basic" ? (
        <TextField
          editable={editable}
          label={t("httpAccounts.fields.username")}
          {...form.fieldProps("username")}
        />
      ) : null}
      {mode === "show" ? (
        <Text size="sm">{t(secretSentence(secretState))}</Text>
      ) : authType === "none" ? null : (
        <TextField
          editable
          type="password"
          autoComplete="new-password"
          label={t("httpAccounts.fields.secret")}
          description={secretDescription(t, mode, authType, form.values.username, baseline)}
          {...form.fieldProps("secret")}
        />
      )}
      <PairSection
        form={form}
        editable={editable}
        keep={mode === "edit"}
        kind="headers"
        title={t("httpAccounts.fields.headers")}
        hint={t("httpAccounts.fields.headersHint")}
        nameLabel={t("httpAccounts.fields.headerName")}
        valueLabel={t("httpAccounts.fields.headerValue")}
        addLabel={t("httpAccounts.fields.addHeader")}
        names={headerNames}
      />
      <PairSection
        form={form}
        editable={editable}
        keep={mode === "edit"}
        kind="query"
        title={t("httpAccounts.fields.query")}
        hint={t("httpAccounts.fields.queryHint")}
        nameLabel={t("httpAccounts.fields.queryName")}
        valueLabel={t("httpAccounts.fields.queryValue")}
        addLabel={t("httpAccounts.fields.addQuery")}
        names={queryNames}
      />
      <OriginSection form={form} editable={editable} />
    </Stack>
  );
}

function PairSection({
  form,
  editable,
  kind,
  keep,
  title,
  hint,
  nameLabel,
  valueLabel,
  addLabel,
  names,
}: {
  form: ReturnType<typeof useConsoleForm<Values>>;
  editable: boolean;
  kind: "headers" | "query";
  keep: boolean;
  title: string;
  hint: string;
  nameLabel: string;
  valueLabel: string;
  addLabel: string;
  names: string[];
}) {
  const t = useTranslate();
  const rows = form.values[kind];
  return (
    <Stack gap="xs">
      <Text size="sm" fw={500}>
        {title}
      </Text>
      <Text size="sm" c="dimmed">
        {hint}
      </Text>
      {editable && keep ? (
        <Text size="sm" c="dimmed">
          {t("httpAccounts.fields.keepList")}
        </Text>
      ) : null}
      {editable
        ? rows.map((_row, index) => (
            <Group key={`${kind}-${index}`} align="flex-start">
              <TextField
                editable
                label={nameLabel}
                style={{ flex: 1 }}
                {...form.fieldProps(`${kind}.${index}.name`)}
              />
              <TextField
                editable
                type="password"
                autoComplete="new-password"
                label={valueLabel}
                style={{ flex: 1 }}
                {...form.fieldProps(`${kind}.${index}.value`)}
              />
              <Button
                type="button"
                mt={24}
                size="sm"
                variant="subtle"
                onClick={() => form.removeListItem(kind, index)}
              >
                {t("httpAccounts.fields.remove")}
              </Button>
            </Group>
          ))
        : names.length === 0
          ? <Text size="sm">{t("httpAccounts.fields.noneListed")}</Text>
          : names.map((name, index) => (
              <Text size="sm" key={`${kind}-name-${index}`}>
                {name}
              </Text>
            ))}
      {editable ? (
        <Button
          type="button"
          size="sm"
          variant="default"
          onClick={() => form.insertListItem(kind, { name: "", value: "" })}
        >
          {addLabel}
        </Button>
      ) : null}
    </Stack>
  );
}

function OriginSection({
  form,
  editable,
}: {
  form: ReturnType<typeof useConsoleForm<Values>>;
  editable: boolean;
}) {
  const t = useTranslate();
  const origins = form.values.origins;
  return (
    <Stack gap="xs">
      <Text size="sm" fw={500}>
        {t("httpAccounts.fields.origins")}
      </Text>
      <Text size="sm" c="dimmed">
        {t("httpAccounts.fields.originsHint")}
      </Text>
      {origins.length === 0 && !editable ? (
        <Text size="sm">{t("httpAccounts.list.anyOrigin")}</Text>
      ) : (
        origins.map((origin, index) => (
          <Group key={`origin-${index}`} align="flex-start">
            <TextField
              editable={editable}
              label={t("httpAccounts.fields.origin")}
              style={{ flex: 1 }}
              {...form.fieldProps(`origins.${index}`)}
            />
            {editable ? (
              <Button
                type="button"
                mt={24}
                size="sm"
                variant="subtle"
                onClick={() => form.removeListItem("origins", index)}
              >
                {t("httpAccounts.fields.remove")}
              </Button>
            ) : null}
          </Group>
        ))
      )}
      {editable ? (
        <Button type="button" size="sm" variant="default" onClick={() => form.insertListItem("origins", "")}>
          {t("httpAccounts.fields.addOrigin")}
        </Button>
      ) : null}
    </Stack>
  );
}

function secretStateOf(account: HttpAccount): "token" | "password" | "empty" {
  if (account.auth.type === "bearer") return "token";
  if (account.auth.type === "basic") return "password";
  return "empty";
}

function secretSentence(state: "token" | "password" | "empty") {
  if (state === "token") return "httpAccounts.fields.tokenSet";
  if (state === "password") return "httpAccounts.fields.passwordSet";
  return "httpAccounts.fields.secretEmpty";
}

function valuesFrom(account: HttpAccount): Values {
  return {
    name: account.name,
    authType: account.auth.type,
    username: account.auth.type === "basic" ? account.auth.username : "",
    secret: "",
    headers: account.headers.map((item) => ({ name: item.name, value: "" })),
    query: account.query.map((item) => ({ name: item.name, value: "" })),
    origins: [...account.allowed_origins],
  };
}

function baselineFrom(account: HttpAccount): Baseline {
  const values = valuesFrom(account);
  return {
    authType: values.authType,
    username: values.username,
    headers: values.headers,
    query: values.query,
  };
}

function samePairs(current: Pair[], initial: Pair[]) {
  if (current.length !== initial.length) return false;
  return current.every(
    (row, index) => row.name === initial[index].name && row.value === initial[index].value,
  );
}

/** Blank secret keeps the stored secret only while the auth identity is unchanged. */
export function blankSecretKeeps(
  authType: HttpAuthType,
  username: string,
  baseline: Pick<Baseline, "authType" | "username"> | null,
): boolean {
  return (
    baseline !== null &&
    authType === baseline.authType &&
    (authType !== "basic" || username === baseline.username)
  );
}

function secretDescription(
  t: (key: string) => string,
  mode: "create" | "show" | "edit",
  authType: HttpAuthType,
  username: string,
  baseline: Baseline | null,
): string {
  if (mode === "edit" && blankSecretKeeps(authType, username, baseline)) {
    return t("httpAccounts.fields.secretKeep");
  }
  if (mode === "edit") return t("httpAccounts.fields.secretRequired");
  return t("httpAccounts.fields.secretHint");
}

function authReplacing(values: Values, baseline: Baseline | null) {
  if (baseline === null) return true;
  return (
    values.authType !== baseline.authType ||
    values.secret !== "" ||
    values.username !== baseline.username
  );
}

function validateAccount(
  values: Values,
  t: (key: string) => string,
  baseline: Baseline | null,
): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!values.name.trim()) errors.name = t("httpAccounts.validation.name");
  const replacing = authReplacing(values, baseline);
  if (values.authType === "basic" && replacing && !values.username.trim()) {
    errors.username = t("httpAccounts.validation.username");
  }
  if (values.authType !== "none" && replacing && !values.secret) {
    errors.secret = t("httpAccounts.validation.secret");
  }
  if (baseline === null || !samePairs(values.headers, baseline.headers)) {
    values.headers.forEach((row, index) => {
      if (!row.name.trim()) errors[`headers.${index}.name`] = t("httpAccounts.validation.headerName");
      if (!row.value) errors[`headers.${index}.value`] = t("httpAccounts.validation.headerValue");
    });
  }
  if (baseline === null || !samePairs(values.query, baseline.query)) {
    values.query.forEach((row, index) => {
      if (!row.name.trim()) errors[`query.${index}.name`] = t("httpAccounts.validation.queryName");
      if (!row.value) errors[`query.${index}.value`] = t("httpAccounts.validation.queryValue");
    });
  }
  values.origins.forEach((origin, index) => {
    if (!origin.trim()) errors[`origins.${index}`] = t("httpAccounts.validation.origin");
  });
  return errors;
}

function writeBody(values: Values, baseline: Baseline | null): HttpAccountWrite {
  const body: HttpAccountWrite = {
    name: values.name.trim(),
    allowed_origins: values.origins.map((origin) => origin.trim()),
  };
  if (authReplacing(values, baseline)) {
    if (values.authType === "none") body.auth = { type: "none" };
    else if (values.authType === "bearer") body.auth = { type: "bearer", token: values.secret };
    else body.auth = { type: "basic", username: values.username.trim(), password: values.secret };
  }
  if (baseline === null || !samePairs(values.headers, baseline.headers)) {
    body.headers = values.headers.map((row) => ({ name: row.name.trim(), value: row.value }));
  }
  if (baseline === null || !samePairs(values.query, baseline.query)) {
    body.query = values.query.map((row) => ({ name: row.name.trim(), value: row.value }));
  }
  return body;
}
