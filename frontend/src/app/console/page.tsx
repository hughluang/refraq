"use client";

import { Text } from "@mantine/core";
import { useGetIdentity, useTranslate } from "@refinedev/core";

import { PageLoader } from "@/components/feedback/PageLoader";
import { PageChrome } from "@/components/layout/PageChrome";
import type { CurrentUser } from "@/providers/session-store";

export default function ConsoleHomePage() {
  const t = useTranslate();
  const { data: user, isLoading } = useGetIdentity<CurrentUser>();

  if (isLoading) {
    return <PageLoader />;
  }

  return (
    <PageChrome title={t("app.title")} description={t("dashboard.description")}>
      {user ? (
        <Text>
          {user.display_name} ({user.account})
          {user.role_name ? ` — ${user.role_name}` : ""}
        </Text>
      ) : (
        <Text c="dimmed">{t("common.empty")}</Text>
      )}
    </PageChrome>
  );
}
