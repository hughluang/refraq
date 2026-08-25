"use client";

import { Text } from "@mantine/core";
import { useGetIdentity, useTranslate } from "@refinedev/core";

import { PageBodySkeleton } from "@/components/feedback/PageBodySkeleton";
import { PageChrome } from "@/components/layout/PageChrome";
import { useBranding } from "@/features/branding/BrandingProvider";
import {
  useSessionStore,
  type CurrentUser,
} from "@/providers/session-store";

export default function ConsoleHomePage() {
  const t = useTranslate();
  const branding = useBranding();
  const { data: identity, isLoading } = useGetIdentity<CurrentUser>();
  const sessionUser = useSessionStore((s) => s.user);
  const user = identity ?? sessionUser;

  return (
    <PageChrome title={branding.brandName} description={t("dashboard.description")}>
      {isLoading && !user ? (
        <PageBodySkeleton rows={3} />
      ) : user ? (
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
