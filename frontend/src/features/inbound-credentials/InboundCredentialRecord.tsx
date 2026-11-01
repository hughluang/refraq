"use client";

import { Button, Group, Stack, Text } from "@mantine/core";
import { useCan, useNotification, useTranslate } from "@refinedev/core";
import { useCallback, useEffect, useRef, useState } from "react";

import { ConfirmActionModal } from "@/components/feedback/ConfirmActionModal";
import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { presentSaveFailure } from "@/components/feedback/presentSaveFailure";
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
  createInboundCredential,
  deleteInboundCredential,
  getInboundCredential,
  patchInboundCredential,
} from "@/features/inbound-credentials/api";
import type {
  HmacConfig,
  HmacEncoding,
  InboundCredential,
  InboundCredentialConfig,
  InboundCredentialCreate,
  InboundCredentialPatch,
  InboundCredentialType,
  TokenConfig,
  TokenLocation,
} from "@/features/inbound-credentials/types";

const FORM_ID = "inbound-credential-record-form";
const LIST_HREF = "/console/inbound-credentials";

type Values = {
  name: string;
  type: InboundCredentialType;
  secret: string;
  location: TokenLocation;
  parameterName: string;
  signatureHeader: string;
  encoding: HmacEncoding;
  prefix: string;
  timestampHeader: string;
};

type Baseline = {
  name: string;
  type: InboundCredentialType;
  config: InboundCredentialConfig;
};

type Props = { mode: "create" } | { mode: "show" | "edit"; credentialId: string };

const EMPTY: Values = {
  name: "",
  type: "token",
  secret: "",
  location: "header",
  parameterName: "",
  signatureHeader: "",
  encoding: "hex",
  prefix: "",
  timestampHeader: "",
};

export function InboundCredentialRecord(props: Props) {
  const mode = props.mode;
  const credentialId = props.mode === "create" ? "" : props.credentialId;
  const t = useTranslate();
  const { replace } = useConsoleNavigation();
  const { open } = useNotification();
  const { data: canWrite } = useCan({
    resource: ModuleId.inboundCredentials,
    action: ModuleAction.edit,
  });
  const baseline = useRef<Baseline | null>(null);
  const [record, setRecord] = useState<InboundCredential | null>(null);
  const [loading, setLoading] = useState(mode !== "create");
  const [loadFailed, setLoadFailed] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const loadRef = useRef<() => void>(() => undefined);
  const form = useConsoleForm<Values>({
    initialValues: EMPTY,
    validate: (values) => validateCredential(values, t, baseline.current),
  });

  const load = useCallback(() => {
    if (!credentialId) return;
    setLoading(true);
    setLoadFailed(false);
    void getInboundCredential(credentialId)
      .then((body) => {
        const credential = body.inbound_credential;
        baseline.current = baselineFrom(credential);
        form.setValues(valuesFrom(credential));
        form.markSaved();
        setRecord(credential);
      })
      .catch((err: unknown) => {
        setLoadFailed(true);
        presentProblemNotification(t, err, { onRetry: () => loadRef.current() });
      })
      .finally(() => setLoading(false));
  }, [credentialId]);

  loadRef.current = load;

  useEffect(() => {
    if (mode === "create") return;
    load();
  }, [load, mode]);

  useEffect(() => {
    if (mode !== "edit" || canWrite?.can !== false || !credentialId) return;
    suppressLeaveGuard();
    replace(`${LIST_HREF}/${credentialId}`);
  }, [canWrite?.can, credentialId, mode, replace]);

  const denied = canWrite?.can === false;
  const editable = mode !== "show" && !denied;
  const showRecord = mode !== "create";

  async function submit(values: Values) {
    if (!editable) return;
    try {
      if (mode === "create") {
        const created = await createInboundCredential(createBody(values));
        form.markSaved();
        suppressLeaveGuard();
        open?.({ type: "success", message: t("inboundCredentials.created") });
        window.location.replace(`${LIST_HREF}/${created.inbound_credential.id}/edit`);
        return;
      }
      if (!credentialId) return;
      const saved = await patchInboundCredential(
        credentialId,
        patchBody(values, baseline.current),
      );
      const credential = saved.inbound_credential;
      baseline.current = baselineFrom(credential);
      form.setValues(valuesFrom(credential));
      form.markSaved();
      setRecord(credential);
      open?.({ type: "success", message: t("inboundCredentials.saved") });
    } catch (error) {
      presentSaveFailure(t, error, form.applyApiError);
    }
  }

  if (showRecord && (loading || !record)) {
    return (
      <PageChrome
        title={t("inboundCredentials.title")}
        status={loadFailed ? "unloaded" : "loading"}
        onRetry={loadFailed ? load : undefined}
      />
    );
  }

  if (mode === "edit" && denied) {
    return <PageChrome title={t("inboundCredentials.title")} status="loading" />;
  }

  const recordTitle = record?.name;
  const showEdit = mode === "show" && !denied;
  const showDelete = showRecord && !denied;
  const showSave = editable;
  const showStandard = showEdit || showDelete || showSave;

  const navigation =
    mode === "create" ? undefined : (
      <Group gap="xs" wrap="nowrap" aria-label={t("inboundCredentials.actions.navigation")}>
        <Button component={ConsoleLink} href={LIST_HREF} variant="default" size="sm">
          {t("inboundCredentials.backToList")}
        </Button>
        <Button variant="default" size="sm" onClick={() => load()}>
          {t("jobs.refresh")}
        </Button>
      </Group>
    );

  const standard = (
    <Group gap="xs" wrap="nowrap" aria-label={t("inboundCredentials.actions.standard")}>
      {showEdit ? (
        <Button
          component={ConsoleLink}
          href={`${LIST_HREF}/${credentialId}/edit`}
          size="sm"
          variant="light"
        >
          {t("actions.edit")}
        </Button>
      ) : null}
      {showDelete ? (
        <Button size="sm" variant="light" color="red" onClick={() => setConfirmDelete(true)}>
          {t("actions.delete")}
        </Button>
      ) : null}
      {mode === "create" ? (
        <Button component={ConsoleLink} href={LIST_HREF} variant="default" size="sm">
          {t("common.cancel")}
        </Button>
      ) : null}
      {mode === "edit" ? (
        <Button
          component={ConsoleLink}
          href={`${LIST_HREF}/${credentialId}`}
          variant="default"
          size="sm"
        >
          {t("common.cancel")}
        </Button>
      ) : null}
      {showSave ? (
        <HeaderAction primary>
          <Button type="submit" form={FORM_ID} size="sm" loading={form.submitting}>
            {mode === "create"
              ? t("inboundCredentials.createSubmit")
              : t("common.save")}
          </Button>
        </HeaderAction>
      ) : null}
    </Group>
  );

  return (
    <PageChrome
      title={mode === "create" ? t("inboundCredentials.createTitle") : t("inboundCredentials.title")}
      recordTitle={recordTitle}
      recent={
        recordTitle
          ? { moduleId: "inbound-credentials", title: recordTitle }
          : undefined
      }
      actions={
        <HeaderActions navigation={navigation} standard={showStandard ? standard : undefined} />
      }
    >
      <form id={FORM_ID} noValidate onSubmit={form.onSubmit((values) => submit(values))}>
        <CredentialFields form={form} editable={editable} mode={mode} />
      </form>
      {confirmDelete ? (
        <ConfirmActionModal
          opened
          onClose={() => setConfirmDelete(false)}
          title={t("inboundCredentials.deleteTitle")}
          body={t("inboundCredentials.deleteConsequence")}
          confirmLabel={t("actions.delete")}
          confirmColor="red"
          loading={deleting}
          onConfirm={() => {
            if (!credentialId) return;
            setDeleting(true);
            void deleteInboundCredential(credentialId)
              .then(() => {
                suppressLeaveGuard();
                open?.({ type: "success", message: t("inboundCredentials.deleted") });
                window.location.assign(LIST_HREF);
              })
              .catch((err: unknown) => {
                setDeleting(false);
                setConfirmDelete(false);
                presentProblemNotification(t, err);
              });
          }}
        />
      ) : null}
    </PageChrome>
  );
}

function CredentialFields({
  form,
  editable,
  mode,
}: {
  form: ReturnType<typeof useConsoleForm<Values>>;
  editable: boolean;
  mode: "create" | "show" | "edit";
}) {
  const t = useTranslate();
  const type = form.values.type;
  const typeOptions = [
    { value: "token", label: t("inboundCredentials.types.token") },
    { value: "hmac_sha256", label: t("inboundCredentials.types.hmac_sha256") },
  ];
  const locationOptions = [
    { value: "header", label: t("inboundCredentials.location.header") },
    { value: "query", label: t("inboundCredentials.location.query") },
  ];
  const encodingOptions = [
    { value: "hex", label: t("inboundCredentials.encoding.hex") },
    { value: "base64", label: t("inboundCredentials.encoding.base64") },
  ];
  return (
    <Stack gap="sm">
      <TextField
        editable={editable}
        label={t("inboundCredentials.fields.name")}
        {...form.fieldProps("name")}
      />
      <SelectField
        editable={editable}
        label={t("inboundCredentials.fields.type")}
        data={typeOptions}
        {...form.fieldProps("type")}
      />
      {type === "token" ? (
        <>
          <SelectField
            editable={editable}
            label={t("inboundCredentials.fields.location")}
            data={locationOptions}
            {...form.fieldProps("location")}
          />
          <TextField
            editable={editable}
            label={t("inboundCredentials.fields.parameterName")}
            description={t("inboundCredentials.fields.parameterHint")}
            {...form.fieldProps("parameterName")}
          />
        </>
      ) : (
        <>
          <TextField
            editable={editable}
            label={t("inboundCredentials.fields.signatureHeader")}
            {...form.fieldProps("signatureHeader")}
          />
          <SelectField
            editable={editable}
            label={t("inboundCredentials.fields.encoding")}
            data={encodingOptions}
            {...form.fieldProps("encoding")}
          />
          <TextField
            editable={editable}
            label={t("inboundCredentials.fields.prefix")}
            description={t("inboundCredentials.fields.prefixHint")}
            {...form.fieldProps("prefix")}
          />
          <TextField
            editable={editable}
            label={t("inboundCredentials.fields.timestampHeader")}
            description={t("inboundCredentials.fields.timestampHint")}
            {...form.fieldProps("timestampHeader")}
          />
        </>
      )}
      {mode === "show" ? (
        <Text size="sm">{t("inboundCredentials.fields.secretSet")}</Text>
      ) : (
        <TextField
          editable={editable}
          type="password"
          autoComplete="new-password"
          label={t("inboundCredentials.fields.secret")}
          description={
            mode === "edit"
              ? t("inboundCredentials.fields.secretKeep")
              : t("inboundCredentials.fields.secretHint")
          }
          {...form.fieldProps("secret")}
        />
      )}
    </Stack>
  );
}

function valuesFrom(record: InboundCredential): Values {
  if (record.type === "hmac_sha256") {
    const config = record.config as HmacConfig;
    return {
      ...EMPTY,
      name: record.name,
      type: "hmac_sha256",
      signatureHeader: config.signature_header ?? "",
      encoding: config.encoding === "base64" ? "base64" : "hex",
      prefix: config.prefix ?? "",
      timestampHeader: config.timestamp_header ?? "",
    };
  }
  const config = record.config as TokenConfig;
  return {
    ...EMPTY,
    name: record.name,
    type: "token",
    location: config.location === "query" ? "query" : "header",
    parameterName: config.name ?? "",
  };
}

function baselineFrom(record: InboundCredential): Baseline {
  const values = valuesFrom(record);
  return { name: values.name, type: values.type, config: configFrom(values) };
}

function configFrom(values: Values): InboundCredentialConfig {
  if (values.type === "token") {
    return { location: values.location, name: values.parameterName.trim() };
  }
  const config: HmacConfig = {
    signature_header: values.signatureHeader.trim(),
    encoding: values.encoding,
  };
  const prefix = values.prefix.trim();
  if (prefix) config.prefix = prefix;
  const timestamp = values.timestampHeader.trim();
  if (timestamp) config.timestamp_header = timestamp;
  return config;
}

function sameConfig(left: InboundCredentialConfig, right: InboundCredentialConfig): boolean {
  return JSON.stringify(left) === JSON.stringify(right);
}

function secretTyped(secret: string): boolean {
  return secret.trim() !== "";
}

function validateCredential(
  values: Values,
  t: (key: string) => string,
  baseline: Baseline | null,
): Record<string, string> {
  const errors: Record<string, string> = {};
  if (!values.name.trim()) errors.name = t("inboundCredentials.validation.name");
  if (values.type === "token") {
    if (!values.parameterName.trim()) {
      errors.parameterName = t("inboundCredentials.validation.parameterName");
    }
  } else if (!values.signatureHeader.trim()) {
    errors.signatureHeader = t("inboundCredentials.validation.signatureHeader");
  }
  if (baseline === null && !secretTyped(values.secret)) {
    errors.secret = t("inboundCredentials.validation.secret");
  }
  return errors;
}

function createBody(values: Values): InboundCredentialCreate {
  return {
    name: values.name.trim(),
    type: values.type,
    secret: values.secret,
    config: configFrom(values),
  };
}

function patchBody(values: Values, baseline: Baseline | null): InboundCredentialPatch {
  const config = configFrom(values);
  const body: InboundCredentialPatch = {};
  const name = values.name.trim();
  if (baseline === null || name !== baseline.name) body.name = name;
  const typeChanged = baseline === null || values.type !== baseline.type;
  const configChanged = baseline === null || !sameConfig(config, baseline.config);
  if (typeChanged) body.type = values.type;
  if (typeChanged || configChanged) body.config = config;
  if (secretTyped(values.secret)) body.secret = values.secret;
  return body;
}
