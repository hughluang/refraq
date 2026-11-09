"use client";

import { Button, Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { PasswordInput } from "@/components/form/PasswordInput";
import {
  useMcpWorkspace,
  type McpPatOutcome,
} from "@/features/mcp/McpWorkspaceProvider";
import { useSessionStore } from "@/providers/session-store";

const API_BASE = process.env.NEXT_PUBLIC_REFRAQ_API_BASE_URL || "/api";

function readUserId(body: unknown): string | null {
  if (typeof body !== "object" || body === null) return null;
  const user = (body as { user?: unknown }).user;
  if (typeof user !== "object" || user === null) return null;
  const id = (user as { id?: unknown }).id;
  if (typeof id !== "string" || id.length === 0) return null;
  return id;
}

export function McpPatGate({ endpoint }: { endpoint: string }) {
  const t = useTranslate();
  const { pat, outcome, setPat, setOutcome } = useMcpWorkspace();

  async function verify() {
    const submitted = pat;
    let next: McpPatOutcome = { status: "auth-error" };
    try {
      // fetch, not apiClient: a 401 from this check must not expire the Console session.
      const response = await fetch(`${API_BASE}/auth/me`, {
        method: "GET",
        credentials: "omit",
        cache: "no-store",
        headers: {
          Accept: "application/json",
          Authorization: `Bearer ${submitted}`,
        },
      });
      if (response.ok) {
        const id = readUserId(await response.json());
        const sessionId = useSessionStore.getState().user?.id;
        if (id !== null && sessionId === id) {
          next = { status: "verified", userId: id };
        } else if (id !== null) {
          next = { status: "rejected" };
        }
      }
    } catch {
      // Thrown fetch or unreadable JSON keeps the authentication outcome.
    }
    setOutcome(submitted, next);
  }

  return (
    <Stack gap="xs">
      <PasswordInput
        label={t("mcp.pat.label")}
        value={pat}
        onChange={(event) => {
          setPat(event.currentTarget.value);
        }}
        autoComplete="off"
      />
      <Button type="button" disabled={pat.length === 0} onClick={() => void verify()}>
        {t("mcp.pat.verify")}
      </Button>
      <Text>{t("mcp.pat.recordsUse")}</Text>
      {outcome.status === "verified" ? (
        <>
          <Text>{`${t("mcp.pat.verified")} ${outcome.userId}`}</Text>
          <Text>{`${t("mcp.pat.endpointLabel")} ${endpoint}`}</Text>
        </>
      ) : null}
      {outcome.status === "rejected" ? <Text>{t("mcp.pat.rejected")}</Text> : null}
      {outcome.status === "auth-error" ? <Text>{t("mcp.pat.authError")}</Text> : null}
    </Stack>
  );
}
