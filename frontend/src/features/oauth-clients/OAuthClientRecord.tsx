"use client";

import {
  Alert,
  Badge,
  Button,
  Code,
  Group,
  MultiSelect,
  NumberInput,
  Select,
  Stack,
  Switch,
  Text,
  Textarea,
  TextInput,
} from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { DisplayField } from "@/components/display/DisplayField";
import { StatusBadge } from "@/components/display/StatusBadge";
import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { FormSection } from "@/components/form/FormSection";
import { PageChrome } from "@/components/layout/PageChrome";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { listIdentityProviders } from "@/features/identity-providers/api";
import type { IdentityProvider } from "@/features/identity-providers/types";
import {
  createOAuthClient,
  deleteOAuthClient,
  getOAuthClient,
  patchOAuthClient,
  rotateOAuthClientSecret,
} from "@/features/oauth-clients/api";
import type {
  OAuthAuthMethod,
  OAuthClient,
} from "@/features/oauth-clients/types";
import { copyText } from "@/lib/copy-text";

const GRANT_OPTIONS = [
  {
    value: "urn:ietf:params:oauth:grant-type:jwt-bearer",
    label: "ID-JAG (jwt-bearer)",
  },
  {
    value: "urn:ietf:params:oauth:grant-type:token-exchange",
    label: "RFC 8693 (token-exchange)",
  },
];

const SURFACE_OPTIONS = [
  { value: "entity_mcp", label: "Entity MCP (/mcp/entity)" },
  { value: "metadata_mcp", label: "Metadata MCP (/mcp)" },
  { value: "api", label: "API (/api)" },
];

const SCOPE_OPTIONS = [
  "entity:data_read",
  "sources:read",
  "metadata:read",
  "metadata:write",
  "query:run",
].map((value) => ({ value, label: value }));

const AUTH_METHOD_OPTIONS: { value: OAuthAuthMethod; label: string }[] = [
  { value: "private_key_jwt", label: "private_key_jwt" },
  { value: "client_secret_basic", label: "client_secret_basic" },
  { value: "client_secret_post", label: "client_secret_post" },
];

export function OAuthClientRecord({
  mode,
  clientId,
}: {
  mode: "create" | "show" | "edit";
  clientId?: string;
}) {
  const t = useTranslate();
  const router = useRouter();
  const { open } = useNotification();

  const [loading, setLoading] = useState(mode !== "create");
  const [saving, setSaving] = useState(false);
  const [record, setRecord] = useState<OAuthClient | null>(null);
  const [providers, setProviders] = useState<IdentityProvider[]>([]);
  const [revealedSecret, setRevealedSecret] = useState<string | null>(null);

  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [providerId, setProviderId] = useState<string | null>(null);
  const [enabled, setEnabled] = useState(true);
  const [authMethod, setAuthMethod] = useState<OAuthAuthMethod>("private_key_jwt");
  const [jwksUri, setJwksUri] = useState("");
  const [jwksText, setJwksText] = useState("");
  const [grantTypes, setGrantTypes] = useState<string[]>([
    "urn:ietf:params:oauth:grant-type:jwt-bearer",
  ]);
  const [audiencesText, setAudiencesText] = useState("");
  const [surfaces, setSurfaces] = useState<string[]>(["entity_mcp"]);
  const [scopes, setScopes] = useState<string[]>(["entity:data_read"]);
  const [ttlSec, setTtlSec] = useState<number | string>(900);

  useEffect(() => {
    void listIdentityProviders({ limit: 100, offset: 0 })
      .then((page) => setProviders(page.items))
      .catch((err: unknown) => presentProblemNotification(t, err));
  }, []);

  useEffect(() => {
    if (mode === "create" || !clientId) return;
    setLoading(true);
    void getOAuthClient(clientId)
      .then(({ oauth_client }) => {
        setRecord(oauth_client);
        setName(oauth_client.name);
        setDescription(oauth_client.description ?? "");
        setProviderId(oauth_client.provider_id);
        setEnabled(oauth_client.enabled);
        setAuthMethod(oauth_client.token_endpoint_auth_method);
        setJwksUri(oauth_client.jwks_uri ?? "");
        setJwksText(
          oauth_client.jwks ? JSON.stringify(oauth_client.jwks, null, 2) : "",
        );
        setGrantTypes(oauth_client.allowed_grant_types);
        setAudiencesText(oauth_client.allowed_subject_audiences.join("\n"));
        setSurfaces(oauth_client.allowed_surfaces);
        setScopes(oauth_client.allowed_scopes);
        setTtlSec(oauth_client.token_ttl_sec ?? 900);
      })
      .catch((err: unknown) => presentProblemNotification(t, err))
      .finally(() => setLoading(false));
  }, [mode, clientId]);

  if (loading) {
    return <PageBodySkeleton />;
  }

  async function handleSubmit() {
    let parsedJwks: Record<string, unknown> | null = null;
    if (jwksText.trim()) {
      try {
        parsedJwks = JSON.parse(jwksText) as Record<string, unknown>;
      } catch {
        open?.({
          type: "error",
          message: t("oauthClients.errors.invalidJwksJson"),
        });
        return;
      }
    }
    const audiences = audiencesText
      .split(/[\n,]/)
      .map((s) => s.trim())
      .filter(Boolean);
    const ttlValue =
      typeof ttlSec === "number" && Number.isFinite(ttlSec) ? ttlSec : null;

    setSaving(true);
    try {
      if (mode === "create") {
        const res = await createOAuthClient({
          name: name.trim(),
          description: description.trim() || null,
          provider_id: providerId ?? "",
          enabled,
          token_endpoint_auth_method: authMethod,
          jwks: parsedJwks,
          jwks_uri: jwksUri.trim() || null,
          allowed_grant_types: grantTypes,
          allowed_subject_audiences: audiences,
          allowed_surfaces: surfaces,
          allowed_scopes: scopes,
          token_ttl_sec: ttlValue,
        });
        if (res.client_secret) {
          setRevealedSecret(res.client_secret);
          setRecord(res.oauth_client);
        } else {
          router.push(`/console/oauth-clients/${res.oauth_client.id}`);
        }
      } else if (clientId) {
        const res = await patchOAuthClient(clientId, {
          name: name.trim(),
          description: description.trim() || null,
          enabled,
          token_endpoint_auth_method: authMethod,
          jwks: parsedJwks,
          jwks_uri: jwksUri.trim() || null,
          allowed_grant_types: grantTypes,
          allowed_subject_audiences: audiences,
          allowed_surfaces: surfaces,
          allowed_scopes: scopes,
          token_ttl_sec: ttlValue,
        });
        setRecord(res.oauth_client);
        router.push(`/console/oauth-clients/${res.oauth_client.id}`);
      }
    } catch (err: unknown) {
      presentProblemNotification(t, err);
    } finally {
      setSaving(false);
    }
  }

  async function handleRotate() {
    if (!clientId) return;
    try {
      const res = await rotateOAuthClientSecret(clientId);
      setRecord(res.oauth_client);
      setRevealedSecret(res.client_secret);
      open?.({ type: "success", message: t("oauthClients.secretRotated") });
    } catch (err: unknown) {
      presentProblemNotification(t, err);
    }
  }

  async function handleDelete() {
    if (!clientId) return;
    try {
      await deleteOAuthClient(clientId);
      router.push("/console/oauth-clients");
    } catch (err: unknown) {
      presentProblemNotification(t, err);
    }
  }

  const readOnly = mode === "show";
  const title =
    mode === "create"
      ? t("oauthClients.create")
      : (record?.name ?? t("oauthClients.title"));

  return (
    <PageChrome
      title={title}
      description={record?.client_id}
      actions={
        readOnly && record ? (
          <Group gap="xs">
            {record.token_endpoint_auth_method !== "private_key_jwt" ? (
              <Button variant="default" onClick={() => void handleRotate()}>
                {t("oauthClients.rotateSecret")}
              </Button>
            ) : null}
            <Button
              component={ConsoleLink}
              href={`/console/oauth-clients/${record.id}/edit`}
            >
              {t("actions.edit")}
            </Button>
            <Button
              color="red"
              variant="subtle"
              onClick={() => void handleDelete()}
            >
              {t("actions.delete")}
            </Button>
          </Group>
        ) : undefined
      }
    >
      <Stack gap="md">
        {revealedSecret ? (
          <Alert color="teal" title={t("oauthClients.secretOnceTitle")}>
            <Stack gap="xs">
              <Text size="sm">{t("oauthClients.secretOnceHint")}</Text>
              <Group gap="xs">
                <Code>{revealedSecret}</Code>
                <Button
                  size="xs"
                  variant="default"
                  onClick={() => void copyText(revealedSecret)}
                >
                  {t("common.copy.label")}
                </Button>
                {record ? (
                  <Button
                    size="xs"
                    onClick={() =>
                      router.push(`/console/oauth-clients/${record.id}`)
                    }
                  >
                    {t("actions.done")}
                  </Button>
                ) : null}
              </Group>
            </Stack>
          </Alert>
        ) : null}

        <FormSection title={t("oauthClients.sections.identity")} columns={2}>
          {readOnly && record ? (
            <>
              <DisplayField
                label={t("oauthClients.fields.clientId")}
                value={<Code>{record.client_id}</Code>}
              />
              <DisplayField
                label={t("oauthClients.fields.status")}
                value={
                  <StatusBadge
                    tone={record.enabled ? "success" : "neutral"}
                    labelKey={
                      record.enabled ? "status.enabled" : "status.disabled"
                    }
                  />
                }
              />
              <DisplayField
                label={t("oauthClients.fields.authMethod")}
                value={<Code>{record.token_endpoint_auth_method}</Code>}
              />
              <DisplayField
                label={t("oauthClients.fields.surfaces")}
                value={
                  <Group gap={4}>
                    {record.allowed_surfaces.map((s) => (
                      <Badge key={s} variant="light">
                        {s}
                      </Badge>
                    ))}
                  </Group>
                }
              />
              <DisplayField
                label={t("oauthClients.fields.scopes")}
                value={
                  <Group gap={4}>
                    {record.allowed_scopes.map((s) => (
                      <Badge key={s} variant="outline">
                        {s}
                      </Badge>
                    ))}
                  </Group>
                }
              />
              <DisplayField
                label={t("oauthClients.fields.grants")}
                value={record.allowed_grant_types.join(", ")}
              />
            </>
          ) : (
            <>
              <TextInput
                label={t("oauthClients.fields.name")}
                value={name}
                onChange={(e) => setName(e.currentTarget.value)}
                required
              />
              <Select
                label={t("oauthClients.fields.provider")}
                data={providers.map((p) => ({
                  value: p.id,
                  label: `${p.display_name} (${p.issuer})`,
                }))}
                value={providerId}
                onChange={setProviderId}
                disabled={mode === "edit"}
                required
              />
              <TextInput
                label={t("oauthClients.fields.description")}
                value={description}
                onChange={(e) => setDescription(e.currentTarget.value)}
              />
              <Switch
                label={t("oauthClients.fields.enabled")}
                checked={enabled}
                onChange={(e) => setEnabled(e.currentTarget.checked)}
                mt="md"
              />
            </>
          )}
        </FormSection>

        {!readOnly ? (
          <>
            <FormSection title={t("oauthClients.sections.auth")} columns={2}>
              <Select
                label={t("oauthClients.fields.authMethod")}
                data={AUTH_METHOD_OPTIONS}
                value={authMethod}
                onChange={(v) =>
                  setAuthMethod((v as OAuthAuthMethod) || "private_key_jwt")
                }
              />
              <NumberInput
                label={t("oauthClients.fields.tokenTtlSec")}
                value={ttlSec}
                onChange={setTtlSec}
                min={60}
                max={3600}
              />
              {authMethod === "private_key_jwt" ? (
                <>
                  <TextInput
                    label={t("oauthClients.fields.jwksUri")}
                    placeholder="https://app.example.com/.well-known/jwks.json"
                    value={jwksUri}
                    onChange={(e) => setJwksUri(e.currentTarget.value)}
                  />
                  <Textarea
                    label={t("oauthClients.fields.jwks")}
                    placeholder='{"keys": [...]}'
                    value={jwksText}
                    onChange={(e) => setJwksText(e.currentTarget.value)}
                    autosize
                    minRows={3}
                  />
                </>
              ) : null}
            </FormSection>

            <FormSection
              title={t("oauthClients.sections.delegation")}
              columns={2}
            >
              <MultiSelect
                label={t("oauthClients.fields.grants")}
                data={GRANT_OPTIONS}
                value={grantTypes}
                onChange={setGrantTypes}
                required
              />
              <MultiSelect
                label={t("oauthClients.fields.surfaces")}
                data={SURFACE_OPTIONS}
                value={surfaces}
                onChange={setSurfaces}
                required
              />
              <MultiSelect
                label={t("oauthClients.fields.scopes")}
                data={SCOPE_OPTIONS}
                value={scopes}
                onChange={setScopes}
                required
              />
              <Textarea
                label={t("oauthClients.fields.subjectAudiences")}
                description={t("oauthClients.fields.subjectAudiencesHelp")}
                value={audiencesText}
                onChange={(e) => setAudiencesText(e.currentTarget.value)}
                autosize
                minRows={2}
              />
            </FormSection>

            <Group justify="flex-end">
              <Button
                variant="default"
                onClick={() => router.push("/console/oauth-clients")}
              >
                {t("actions.cancel")}
              </Button>
              <Button loading={saving} onClick={() => void handleSubmit()}>
                {t("actions.save")}
              </Button>
            </Group>
          </>
        ) : null}
      </Stack>
    </PageChrome>
  );
}
