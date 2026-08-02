"use client";

import {
  Anchor,
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
import { Suspense, useState, type FormEvent } from "react";

import { LangSwitcher } from "@/components/LangSwitcher";
import { resolveFromPath } from "@/lib/return-path";

function LoginForm() {
  const t = useTranslate();
  const searchParams = useSearchParams();
  const { mutate: login, isPending } = useLogin<{
    account: string;
    password: string;
  }>();
  const [account, setAccount] = useState("");
  const [password, setPassword] = useState("");

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

export default function LoginPage() {
  const t = useTranslate();

  return (
    <Suspense fallback={<LoginFallback />}>
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
            <LoginForm />
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
