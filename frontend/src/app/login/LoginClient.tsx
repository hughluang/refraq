"use client";

import {
  Anchor,
  Divider,
  Button,
  Center,
  Paper,
  Skeleton,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { PasswordInput } from "@/components/form/PasswordInput";
import { TextField } from "@/components/form/TextField";
import { BrandMark } from "@/components/display/BrandMark";
import { useLogin, useTranslate } from "@refinedev/core";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState, type FormEvent } from "react";

import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { LangSwitcher } from "@/components/LangSwitcher";
import { useBranding } from "@/features/branding/BrandingProvider";
import { resolveFromPath } from "@/lib/return-path";
import {
  probeLoginSession,
  type LoginSessionProbe,
} from "@/providers/auth-provider";
import { presentConsoleNotification } from "@/providers/notification-provider";
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

  const loadProviders = useCallback(() => {
    void apiClient<{ items: PublicAuthProvider[] }>("/auth/providers")
      .then((data) => {
        setProviders(data.items);
      })
      .catch((err: unknown) => {
        setProviders([]);
        if (err instanceof ApiError) {
          presentProblemNotification(t, err, { onRetry: loadProviders });
          return;
        }
        presentLoadFailure(t, loadProviders, t("auth.login.error.network"));
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
            presentConsoleNotification({
              type: "error",
              title: passwordFailureTitle(result.error, t),
            });
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
        <TextField
          editable
          label={t("auth.login.account")}
          value={account}
          onChange={(event) => {
            setAccount(event.currentTarget.value);
          }}
          required
          autoComplete="username"
        />
        <PasswordInput
          label={t("auth.login.password")}
          value={password}
          onChange={(event) => {
            setPassword(event.currentTarget.value);
          }}
          required
          autoComplete="current-password"
        />
        <Button type="submit" loading={isPending} fullWidth>
          {t("auth.login.submit")}
        </Button>
        {providers.length ? (
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
      <Paper
        p="xl"
        withBorder
        w={380}
        aria-busy="true"
        aria-label={t("common.loading")}
      >
        <Stack gap="md">
          <Skeleton height={18} width="30%" ml="auto" />
          <Skeleton height={64} width="45%" />
          <Skeleton height={22} width="55%" />
          <Skeleton height={36} />
          <Skeleton height={36} />
          <Skeleton height={36} />
        </Stack>
      </Paper>
    </Center>
  );
}

const PASSWORD_FAILURE_KEYS = [
  "auth.login.error.invalidCredentials",
  "auth.login.error.network",
  "auth.login.error.consoleAccess",
  "auth.login.error.disabled",
] as const;

function passwordFailureTitle(error: unknown, t: (key: string) => string): string {
  const fallback = t("auth.login.error.invalidCredentials");
  const message = loginFailureText(error, fallback);
  const allowed = new Set(PASSWORD_FAILURE_KEYS.map((key) => t(key)));
  return allowed.has(message) ? message : fallback;
}

function loginFailureText(error: unknown, fallback: string): string {
  if (
    error
    && typeof error === "object"
    && "message" in error
    && typeof error.message === "string"
    && error.message
  ) {
    return error.message;
  }
  return fallback;
}

type LoginGateView = "probing" | "form";

function presentLoadFailure(
  t: (key: string) => string,
  onRetry: () => void,
  title = t("common.error.loadFailed"),
) {
  presentConsoleNotification({
    type: "error",
    title,
    message: (
      <Button type="button" size="compact-xs" variant="subtle" onClick={onRetry}>
        {t("common.retry")}
      </Button>
    ),
  });
}

function applyLoginProbe(
  result: LoginSessionProbe,
  fromPath: string,
  setView: (view: "form") => void,
  onLoadError: () => void,
) {
  if (result === "active") {
    window.location.assign(fromPath);
    return;
  }
  setView("form");
  if (result === "load_error") onLoadError();
}

function LoginGate() {
  const t = useTranslate();
  const branding = useBranding();
  const searchParams = useSearchParams();
  const errorCode = searchParams.get("error");
  const [view, setView] = useState<LoginGateView>("probing");
  const fromPath = resolveFromPath(searchParams.get("from"));
  const fromPathRef = useRef(fromPath);
  fromPathRef.current = fromPath;
  const tRef = useRef(t);
  tRef.current = t;

  const reportProbe = useCallback((result: LoginSessionProbe) => {
    applyLoginProbe(result, fromPathRef.current, setView, () => {
      presentLoadFailure(tRef.current, () => {
        void probeLoginSession().then(reportProbe);
      });
    });
  }, []);

  useEffect(() => {
    let cancelled = false;
    void probeLoginSession().then((result) => {
      if (cancelled) {
        return;
      }
      reportProbe(result);
    });
    return () => {
      cancelled = true;
    };
  }, [fromPath, reportProbe]);

  useEffect(() => {
    if (!errorCode) return;
    if (errorCode === "AUTH_SSO_NOT_ADMITTED") {
      presentConsoleNotification({
        type: "warning",
        title: t("auth.login.sso.pendingTitle"),
        message: t("auth.login.error.AUTH_SSO_NOT_ADMITTED"),
      });
      return;
    }
    presentConsoleNotification({
      type: "error",
      title: t(`auth.login.error.${errorCode}`, {
        defaultValue: t("auth.login.error.sso"),
      }),
    });
  }, [errorCode, t]);

  if (view === "probing") {
    return <LoginFallback />;
  }

  return (
    <Center mih="100vh" p="md">
      <Paper p="xl" withBorder w={380}>
        <Stack gap="md">
          <GroupHeader />
          <Stack gap={0}>
            {branding.logoUrl ? (
              <BrandMark src={branding.logoUrl} alt={branding.brandName} height={64} />
            ) : null}
            {branding.raw.show_brand_name_with_logo ? (
              <Title order={3}>{branding.brandName}</Title>
            ) : null}
            {branding.tagline ? (
              <Text size="sm" c="dimmed">
                {branding.tagline}
              </Text>
            ) : null}
          </Stack>
          <LoginForm />
          <Anchor
            fz={10}
            lh={1.3}
            c="dimmed"
            underline="hover"
            display="block"
            ta="center"
            href="https://github.com/hughluang/refraq"
            target="_blank"
            rel="noreferrer"
          >
            Refraq
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
