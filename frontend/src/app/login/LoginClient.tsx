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
import { ProblemDetails } from "@/components/feedback/ProblemDetails";
import { useTranslate } from "@refinedev/core";
import { useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useRef, useState, type FormEvent } from "react";

import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import { LangSwitcher } from "@/components/LangSwitcher";
import { useBranding } from "@/features/branding/BrandingProvider";
import { resolveFromPath } from "@/lib/return-path";
import {
  probeLoginSession,
  signIn,
  type LoginSessionProbe,
} from "@/providers/auth-provider";
import { presentConsoleNotification } from "@/providers/notification-provider";
import { ApiError, apiClient } from "@/lib/api";
import type { PublicAuthProvider } from "@/features/identity-providers/types";

function LoginForm() {
  const t = useTranslate();
  const searchParams = useSearchParams();
  const [account, setAccount] = useState("");
  const [password, setPassword] = useState("");
  const [pending, setPending] = useState(false);
  const pendingRef = useRef(false);
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
    if (pendingRef.current) return;
    pendingRef.current = true;
    setPending(true);
    void signIn({ account, password })
      .then(() => {
        // Hard navigation avoids Refine soft go() + App Router replace/refresh
        // races that leave the client stuck after a successful login.
        window.location.assign(resolveFromPath(searchParams.get("from")));
      })
      .catch((error: unknown) => {
        presentLoginFailure(t, error);
        pendingRef.current = false;
        setPending(false);
      });
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
        <Button type="submit" loading={pending} fullWidth>
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

type Translate = (key: string) => string;

function loginDetailLabels(t: Translate) {
  return {
    summary: t("form.error.details"),
    requestId: t("common.requestId"),
    copy: t("form.error.copy"),
    copied: t("common.copy.success"),
    copyFailed: t("common.copy.failed"),
  };
}

/** Known login sentences stay the main line. Detail and request id sit in the disclosure. */
function presentLoginSentence(t: Translate, title: string, error: ApiError) {
  const detail = error.detail.trim() ? error.detail : null;
  const requestId = error.requestId?.trim() ? error.requestId : null;
  const disclosure =
    detail || requestId ? (
      <ProblemDetails detail={detail} requestId={requestId} labels={loginDetailLabels(t)} />
    ) : null;
  presentConsoleNotification({
    type: "error",
    title,
    message: disclosure ?? "",
  });
}

function presentLoginFailure(t: Translate, error: unknown) {
  if (!(error instanceof ApiError)) {
    presentConsoleNotification({
      type: "error",
      title: t("auth.login.error.network"),
    });
    return;
  }
  if (error.status === 401) {
    presentLoginSentence(t, t("auth.login.error.invalidCredentials"), error);
    return;
  }
  if (error.status === 403) {
    const title =
      error.code === "AUTH_CONSOLE_ACCESS_REQUIRED"
        ? t("auth.login.error.consoleAccess")
        : t("auth.login.error.disabled");
    presentLoginSentence(t, title, error);
    return;
  }
  presentProblemNotification(t, error);
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
  onLoadError: (error: unknown) => void,
) {
  if (result.status === "active") {
    window.location.assign(fromPath);
    return;
  }
  setView("form");
  if (result.status === "load_error") onLoadError(result.error);
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
    applyLoginProbe(result, fromPathRef.current, setView, (error) => {
      const retry = () => {
        void probeLoginSession().then(reportProbe);
      };
      if (error instanceof ApiError) {
        presentProblemNotification(tRef.current, error, { onRetry: retry });
        return;
      }
      presentLoadFailure(tRef.current, retry);
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
    const id = `login-error:${errorCode}`;
    if (errorCode === "AUTH_SSO_NOT_ADMITTED") {
      presentConsoleNotification({
        id,
        type: "warning",
        title: t("auth.login.sso.pendingTitle"),
        message: t("auth.login.error.AUTH_SSO_NOT_ADMITTED"),
      });
      return;
    }
    presentConsoleNotification({
      id,
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
