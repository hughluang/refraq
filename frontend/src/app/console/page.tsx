"use client";

import { Stack, Text, Title } from "@mantine/core";
import { useGetIdentity, useTranslate } from "@refinedev/core";

import { PageLoader } from "@/components/feedback/PageLoader";
import type { CurrentUser } from "@/providers/session-store";

export default function ConsoleHomePage() {
  const t = useTranslate();
  const { data: user, isLoading } = useGetIdentity<CurrentUser>();

  if (isLoading) {
    return <PageLoader />;
  }

  return (
    <Stack gap="md">
      <Title order={2}>{t("app.title")}</Title>
      {user ? (
        <Text>
          {user.display_name} ({user.account})
          {user.role_name ? ` — ${user.role_name}` : ""}
        </Text>
      ) : (
        <Text c="dimmed">{t("common.empty")}</Text>
      )}
    </Stack>
  );
}
