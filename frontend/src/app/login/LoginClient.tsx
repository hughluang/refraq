"use client";

import {
  Alert,
  Anchor,
  Divider,
  Button,
  Center,
  Paper,
  PasswordInput,
  Stack,
  Text,
  TextInput,
  Title,
} from "@mantine/core";
import { useLogin, useTranslate } from "@refinedev/core";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState, type FormEvent } from "react";

import { PageError } from "@/components/feedback/PageError";
import { LangSwitcher } from "@/components/LangSwitcher";
import { resolveFromPath } from "@/lib/return-path";
import {
  probeLoginSession,
  type LoginSessionProbe,
} from "@/providers/auth-provider";
import { useSessionStore } from "@/providers/session-store";
import { ApiError, apiClient } from "@/lib/api";
import type { PublicAuthProvider } from "@/features/identity-providers/types";

function LoginForm() {
  const t = useTranslate();
  const searchParams = useSearchParams();
  const { mutate: login, isPending } = useLogin<{
    account: string;
    password: string;
  }>();
  const [account, setAccount] = useState("");
  const [password, setPassword] = useState("");
  const [providers, setProviders] = useState<PublicAuthProvider[]>([]);
  const [providersError, setProvidersError] = useState<string | null>(null);

  const loadProviders = useCallback(() => {
    void apiClient<{ items: PublicAuthProvider[] }>("/auth/providers")
      .then((data) => {
        setProviders(data.items);
        setProvidersError(null);
      })
      .catch((err: unknown) => {
        setProviders([]);
        setProvidersError(
          err instanceof ApiError ? err.detail : t("common.error.loadFailed"),
        );
      });
  }, [t]);

  useEffect(() => {
    loadProviders();
  }, [loadProviders]);

  function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    login(
      { account, password },
      {
        onSuccess: (result) => {
          if (!result.success) {
            return;
          }
          // Hard navigation avoids Refine soft go() + App Router replace/refresh
          // races that leave the client stuck after a successful login.
          window.location.assign(resolveFromPath(searchParams.get("from")));
        },
      },
    );
  }

  return (
    <form onSubmit={onSubmit}>
      <Stack gap="sm">
        <TextInput
          label={t("auth.login.account")}
          value={account}
          onChange={(event) => setAccount(event.currentTarget.value)}
          required
          autoComplete="username"
        />
        <PasswordInput
          label={t("auth.login.password")}
          value={password}
          onChange={(event) => setPassword(event.currentTarget.value)}
          required
          autoComplete="current-password"
        />
        <Button type="submit" loading={isPending} fullWidth>
          {t("auth.login.submit")}
        </Button>
        {providersError ? (
          <PageError message={providersError} onRetry={loadProviders} />
        ) : providers.length ? (
          <>
            <Divider label={t("auth.login.ssoDivider")} />
            <Stack gap="xs">
              {providers.map((provider) => (
                <Button
                  key={provider.id}
                  variant="light"
                  component="a"
                  href={`/api/auth/sso/${encodeURIComponent(provider.id)}/start?from=${encodeURIComponent(resolveFromPath(searchParams.get("from")))}`}
                >
                  {provider.display_name}
                </Button>
              ))}
            </Stack>
          </>
        ) : null}
      </Stack>
    </form>
  );
}

function LoginFallback() {
  const t = useTranslate();
  return (
    <Center mih="100vh" p="md">
      <Paper p="xl" withBorder w={380}>
        <Text c="dimmed">{t("common.loading")}</Text>
      </Paper>
    </Center>
  );
}

type LoginGateView = "probing" | "form" | "load_error";

function applyLoginProbe(
  result: LoginSessionProbe,
  fromPath: string,
  setView: (view: Exclude<LoginGateView, "probing">) => void,
) {
  if (result === "active") {
    window.location.assign(fromPath);
    return;
  }
  setView(result === "load_error" ? "load_error" : "form");
}

function LoginGate() {
  const t = useTranslate();
  const searchParams = useSearchParams();
  const identityError = useSessionStore((s) => s.identityError);
  const errorCode = searchParams.get("error");
  const [view, setView] = useState<LoginGateView>("probing");
  const fromPath = resolveFromPath(searchParams.get("from"));

  useEffect(() => {
    let cancelled = false;
    void probeLoginSession().then((result) => {
      if (cancelled) {
        return;
      }
      applyLoginProbe(result, fromPath, setView);
    });
    return () => {
      cancelled = true;
    };
  }, [fromPath]);

  if (view === "probing") {
    return <LoginFallback />;
  }

  return (
    <Center mih="100vh" p="md">
      <Paper p="xl" withBorder w={380}>
        <Stack gap="md">
          <GroupHeader />
          <Stack gap={0}>
            <Title order={3}>{t("app.title")}</Title>
            <Text size="sm" c="dimmed">
              {t("app.description")}
            </Text>
          </Stack>
          {view === "load_error" ? (
            <PageError
              message={
                identityError === "identity_load_failed" || !identityError
                  ? t("common.error.loadFailed")
                  : identityError
              }
              onRetry={() => {
                void probeLoginSession().then((result) => {
                  applyLoginProbe(result, fromPath, setView);
                });
              }}
            />
          ) : (
            <>
              {errorCode === "AUTH_SSO_NOT_ADMITTED" ? (
                <Alert
                  color="yellow"
                  title={t("auth.login.sso.pendingTitle")}
                >
                  {t("auth.login.error.AUTH_SSO_NOT_ADMITTED")}
                </Alert>
              ) : errorCode ? (
                <PageError
                  message={t(`auth.login.error.${errorCode}`, {
                    defaultValue: t("auth.login.error.sso"),
                  })}
                />
              ) : null}
              <LoginForm />
            </>
          )}
          <Anchor
            size="xs"
            href="https://github.com/hughluang/refraq"
            target="_blank"
          >
            refraq
          </Anchor>
        </Stack>
      </Paper>
    </Center>
  );
}

export default function LoginPage() {
  return (
    <Suspense fallback={<LoginFallback />}>
      <LoginGate />
    </Suspense>
  );
}

function GroupHeader() {
  return (
    <Stack align="flex-end">
      <LangSwitcher />
    </Stack>
  );
}
