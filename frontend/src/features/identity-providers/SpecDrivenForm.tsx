"use client";

import {
  Button,
  Group,
  Select,
  Stack,
  Switch,
  Text,
  TextInput,
} from "@mantine/core";
import { useForm } from "@mantine/form";
import { useList, useTranslate } from "@refinedev/core";
import { useEffect, useMemo, useState } from "react";

import { DisplayField } from "@/components/display/DisplayField";
import { ModuleId } from "@/features/console/module-identity";
import type { RoleRow } from "@/features/roles/types";
import { getIdentityProviderSpec } from "@/features/identity-providers/api";
import type {
  IdentityProvider,
  IdentityProviderFormValues,
  IdentityProviderSpec,
  IdentityProviderWrite,
} from "@/features/identity-providers/types";
import type { JsonSchemaProperty } from "@/lib/json-schema";

type Props = {
  provider?: IdentityProvider;
  loading?: boolean;
  onSubmit: (values: IdentityProviderFormValues) => void;
  onCancel: () => void;
};

const SPEC_FORM_KEYS = [
  "issuer",
  "client_id",
  "client_secret",
  "scopes",
  "auto_provision",
  "group_claim",
  "group_allowlist",
  "default_role_id",
] as const;

type SpecFormKey = (typeof SPEC_FORM_KEYS)[number];

export function splitCsv(value: string): string[] {
  return value
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function joinCsv(values: string[]): string {
  return values.join(", ");
}

function emptyValues(): IdentityProviderFormValues {
  return {
    display_name: "",
    protocol: "oidc",
    enabled: true,
    issuer: "",
    client_id: "",
    client_secret: "",
    scopes: "openid, profile, email",
    auto_provision: false,
    group_claim: "groups",
    group_allowlist: "",
    default_role_id: null,
  };
}

export function valuesFromProvider(
  provider?: IdentityProvider,
): IdentityProviderFormValues {
  if (!provider) return emptyValues();
  return {
    display_name: provider.display_name,
    protocol: "oidc",
    enabled: provider.enabled,
    issuer: provider.issuer,
    client_id: provider.client_id,
    client_secret: "",
    scopes: joinCsv(provider.scopes),
    auto_provision: provider.auto_provision,
    group_claim: provider.group_claim,
    group_allowlist: joinCsv(provider.group_allowlist),
    default_role_id: provider.default_role_id,
  };
}

export function providerPayload(
  values: IdentityProviderFormValues,
  mode: "create" | "edit",
): IdentityProviderWrite {
  const payload: IdentityProviderWrite = {
    display_name: values.display_name.trim(),
    enabled: values.enabled,
    client_id: values.client_id.trim(),
    auto_provision: values.auto_provision,
    group_claim: values.group_claim.trim() || "groups",
    group_allowlist: splitCsv(values.group_allowlist),
    scopes: splitCsv(values.scopes),
  };
  if (mode === "create") {
    payload.protocol = "oidc";
    payload.issuer = values.issuer.trim();
  }
  if (values.client_secret.trim()) {
    payload.client_secret = values.client_secret;
  }
  if (values.default_role_id) {
    payload.default_role_id = values.default_role_id;
  }
  if (payload.scopes?.length === 0) {
    delete payload.scopes;
  }
  return payload;
}

function propType(prop: JsonSchemaProperty | undefined): string {
  const type = prop?.type;
  if (Array.isArray(type)) return type[0] ?? "string";
  return type ?? "string";
}

export function SpecDrivenForm({
  provider,
  loading,
  onSubmit,
  onCancel,
}: Props) {
  const t = useTranslate();
  const [spec, setSpec] = useState<IdentityProviderSpec | null>(null);
  const [callbackUrl, setCallbackUrl] = useState("");
  const roles = useList<RoleRow>({
    resource: ModuleId.roles,
    pagination: { mode: "off" },
  });
  const form = useForm<IdentityProviderFormValues>({
    initialValues: valuesFromProvider(provider),
    validate: {
      display_name: (value) =>
        value.trim() ? null : t("identityProviders.validation.required"),
      issuer: (value) =>
        value.trim() ? null : t("identityProviders.validation.required"),
      client_id: (value) =>
        value.trim() ? null : t("identityProviders.validation.required"),
      client_secret: (value) =>
        provider || value.trim()
          ? null
          : t("identityProviders.validation.required"),
      group_allowlist: (value, values) =>
        values.auto_provision && splitCsv(value).length === 0
          ? t("identityProviders.validation.required")
          : null,
      default_role_id: (value, values) =>
        values.auto_provision && !value
          ? t("identityProviders.validation.required")
          : null,
    },
  });

  useEffect(() => {
    void getIdentityProviderSpec("oidc")
      .then((data) => setSpec(data.spec))
      .catch(() => setSpec(null));
  }, []);

  useEffect(() => {
    if (!provider || typeof window === "undefined") {
      setCallbackUrl("");
      return;
    }
    setCallbackUrl(
      `${window.location.origin}/api/auth/sso/${provider.id}/callback`,
    );
  }, [provider]);

  const required = useMemo(
    () => new Set(spec?.required ?? ["issuer", "client_id"]),
    [spec?.required],
  );
  const properties = spec?.properties ?? {};
  const specKeys = spec
    ? SPEC_FORM_KEYS.filter((key) => {
        const prop = properties[key];
        if (!prop) return false;
        return propType(prop) !== "object";
      })
    : [...SPEC_FORM_KEYS];

  const roleOptions = (roles.result?.data ?? []).map((role) => ({
    value: role.id,
    label: role.name,
  }));

  const fieldLabel = (key: string, markRequired: boolean) =>
    `${t(`identityProviders.fields.${key}`)}${markRequired ? " *" : ""}`;

  const renderSpecField = (key: SpecFormKey) => {
    const prop = properties[key];
    const markRequired =
      required.has(key) ||
      (key === "client_secret" && !provider) ||
      (key === "group_allowlist" && form.values.auto_provision) ||
      (key === "default_role_id" && form.values.auto_provision);
    const label = fieldLabel(key, markRequired);
    const description = prop?.description;

    if (key === "issuer") {
      if (provider) {
        return (
          <DisplayField
            key={key}
            label={label}
            description={t("identityProviders.fields.issuerLocked")}
            value={form.values.issuer}
          />
        );
      }
      return (
        <TextInput
          key={key}
          label={label}
          description={description}
          {...form.getInputProps("issuer")}
        />
      );
    }

    if (key === "default_role_id") {
      return (
        <Select
          key={key}
          label={label}
          description={description}
          data={roleOptions}
          clearable
          value={form.values.default_role_id}
          onChange={(value) => form.setFieldValue("default_role_id", value)}
        />
      );
    }

    if (key === "auto_provision" || propType(prop) === "boolean") {
      return (
        <Switch
          key={key}
          label={label}
          description={description}
          {...form.getInputProps(key, { type: "checkbox" })}
        />
      );
    }

    if (key === "client_secret" || prop?.["x-secret"]) {
      return (
        <TextInput
          key={key}
          label={label}
          description={
            provider?.client_secret_configured
              ? t("identityProviders.fields.client_secret_configured")
              : description
          }
          type="password"
          autoComplete="new-password"
          {...form.getInputProps("client_secret")}
        />
      );
    }

    return (
      <TextInput
        key={key}
        label={label}
        description={description}
        {...form.getInputProps(key)}
      />
    );
  };

  return (
    <form onSubmit={form.onSubmit(onSubmit)}>
      <Stack gap="sm">
        <TextInput
          label={fieldLabel("display_name", true)}
          {...form.getInputProps("display_name")}
        />
        <TextInput
          label={t("identityProviders.fields.protocol")}
          value={form.values.protocol}
          disabled
        />
        <Switch
          label={t("identityProviders.fields.enabled")}
          {...form.getInputProps("enabled", { type: "checkbox" })}
        />
        {callbackUrl ? (
          <DisplayField
            label={t("identityProviders.fields.callbackUrl")}
            description={t("identityProviders.fields.callbackUrlHint")}
            value={callbackUrl}
          />
        ) : null}
        {specKeys.map((key) => renderSpecField(key))}
        {spec?.$id ? (
          <Text size="xs" c="dimmed" ff="monospace">
            {spec.$id}
          </Text>
        ) : null}
        <Group justify="flex-end">
          <Button variant="default" onClick={onCancel} disabled={loading}>
            {t("common.cancel")}
          </Button>
          <Button type="submit" loading={loading}>
            {t("common.save")}
          </Button>
        </Group>
      </Stack>
    </form>
  );
}
