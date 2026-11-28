"use client";

import {
  Alert,
  Button,
  Code,
  Group,
  Modal,
  Stack,
  Table,
  Text,
  TextInput,
} from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import { useCallback, useEffect, useState } from "react";

import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import {
  createScimToken,
  listScimTokens,
  revokeScimToken,
} from "@/features/identity-providers/api";
import type {
  IdentityProvider,
  ScimToken,
} from "@/features/identity-providers/types";
import { copyText } from "@/lib/copy-text";

export function ScimTokensModal({
  provider,
  onClose,
}: {
  provider: IdentityProvider | null;
  onClose: () => void;
}) {
  const t = useTranslate();
  const { open } = useNotification();
  const [tokens, setTokens] = useState<ScimToken[]>([]);
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [revealedToken, setRevealedToken] = useState<string | null>(null);

  const load = useCallback(async (providerId: string) => {
    try {
      const res = await listScimTokens(providerId);
      setTokens(res.items);
    } catch (err: unknown) {
      presentProblemNotification(t, err);
    }
  }, [t]);

  useEffect(() => {
    if (!provider) {
      setTokens([]);
      setRevealedToken(null);
      setName("");
      return;
    }
    void load(provider.id);
  }, [provider, load]);

  async function handleCreate() {
    if (!provider || !name.trim()) return;
    setCreating(true);
    try {
      const res = await createScimToken(provider.id, name.trim());
      setRevealedToken(res.token);
      setName("");
      await load(provider.id);
    } catch (err: unknown) {
      presentProblemNotification(t, err);
    } finally {
      setCreating(false);
    }
  }

  async function handleRevoke(tokenId: string) {
    if (!provider) return;
    try {
      await revokeScimToken(provider.id, tokenId);
      open?.({ type: "success", message: t("identityProviders.scim.revoked") });
      await load(provider.id);
    } catch (err: unknown) {
      presentProblemNotification(t, err);
    }
  }

  const scimEndpoint =
    typeof window !== "undefined"
      ? `${window.location.origin}/api/scim/v2`
      : "/api/scim/v2";

  return (
    <Modal
      stackId="identity-provider-scim"
      opened={provider !== null}
      onClose={onClose}
      title={
        provider
          ? `${t("identityProviders.scim.title")} — ${provider.display_name}`
          : t("identityProviders.scim.title")
      }
      size="lg"
    >
      <Stack gap="md">
        <Group gap="xs" wrap="wrap">
          <Text size="sm" fw={500}>
            {t("identityProviders.scim.endpoint")}:
          </Text>
          <Code>{scimEndpoint}</Code>
          <Button
            size="xs"
            variant="default"
            onClick={() => void copyText(scimEndpoint)}
          >
            {t("common.copy.label")}
          </Button>
        </Group>

        {revealedToken ? (
          <Alert color="teal" title={t("identityProviders.scim.tokenOnceTitle")}>
            <Stack gap="xs">
              <Text size="sm">{t("identityProviders.scim.tokenOnceHint")}</Text>
              <Group gap="xs">
                <Code>{revealedToken}</Code>
                <Button
                  size="xs"
                  variant="default"
                  onClick={() => void copyText(revealedToken)}
                >
                  {t("common.copy.label")}
                </Button>
              </Group>
            </Stack>
          </Alert>
        ) : null}

        <Group align="flex-end">
          <TextInput
            style={{ flex: 1 }}
            label={t("identityProviders.scim.tokenName")}
            placeholder="Okta SCIM"
            value={name}
            onChange={(e) => setName(e.currentTarget.value)}
          />
          <Button
            loading={creating}
            disabled={!name.trim()}
            onClick={() => void handleCreate()}
          >
            {t("identityProviders.scim.mint")}
          </Button>
        </Group>

        <Table>
          <Table.Thead>
            <Table.Tr>
              <Table.Th>{t("identityProviders.scim.tokenName")}</Table.Th>
              <Table.Th>{t("identityProviders.scim.prefix")}</Table.Th>
              <Table.Th />
            </Table.Tr>
          </Table.Thead>
          <Table.Tbody>
            {tokens.length === 0 ? (
              <Table.Tr>
                <Table.Td colSpan={3}>
                  <Text size="sm" c="dimmed">
                    {t("identityProviders.scim.empty")}
                  </Text>
                </Table.Td>
              </Table.Tr>
            ) : (
              tokens.map((item) => (
                <Table.Tr key={item.id}>
                  <Table.Td>{item.name}</Table.Td>
                  <Table.Td>
                    <Code>{item.prefix}…</Code>
                  </Table.Td>
                  <Table.Td>
                    <Button
                      size="xs"
                      color="red"
                      variant="subtle"
                      onClick={() => void handleRevoke(item.id)}
                    >
                      {t("actions.revoke")}
                    </Button>
                  </Table.Td>
                </Table.Tr>
              ))
            )}
          </Table.Tbody>
        </Table>
      </Stack>
    </Modal>
  );
}
