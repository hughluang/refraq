"use client";

import {
  AppShell,
  Burger,
  Button,
  Group,
  Stack,
  Text,
  Title,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import {
  useGetIdentity,
  useLogout,
  useTranslate,
} from "@refinedev/core";
import type { ReactNode } from "react";
import { useCallback, useEffect, useState } from "react";
import { usePathname } from "next/navigation";

import { PageError } from "@/components/feedback/PageError";
import { PageLoader } from "@/components/feedback/PageLoader";
import { ConsoleNavLink } from "@/components/layout/ConsoleNavLink";
import { LangSwitcher } from "@/components/LangSwitcher";
import { fetchConsoleNavigation } from "@/features/console/api";
import type { NavigationGroup } from "@/features/console/types";
import { ApiError } from "@/lib/api";
import type { CurrentUser } from "@/providers/session-store";

type ConsoleShellProps = { children: ReactNode };

export function ConsoleShell({ children }: ConsoleShellProps) {
  const t = useTranslate();
  const pathname = usePathname();
  const [opened, { toggle }] = useDisclosure();
  const { data: user } = useGetIdentity<CurrentUser>();
  const { mutate: logout, isPending } = useLogout();
  const [groups, setGroups] = useState<NavigationGroup[] | null>(null);
  const [navError, setNavError] = useState<string | null>(null);
  const [navLoading, setNavLoading] = useState(true);

  const loadNavigation = useCallback(async () => {
    setNavLoading(true);
    setNavError(null);
    try {
      const data = await fetchConsoleNavigation();
      setGroups(data.groups);
    } catch (error) {
      setGroups(null);
      setNavError(
        error instanceof ApiError ? error.detail : "navigation_load_failed",
      );
    } finally {
      setNavLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadNavigation();
  }, [loadNavigation]);

  return (
    <AppShell
      header={{ height: 56 }}
      navbar={{
        width: 220,
        breakpoint: "sm",
        collapsed: { mobile: !opened },
      }}
      padding="md"
    >
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between">
          <Group gap="sm">
            <Burger opened={opened} onClick={toggle} hiddenFrom="sm" size="sm" />
            <Title order={4}>{t("layout.consoleTitle")}</Title>
          </Group>
          <Group gap="sm">
            {user ? (
              <Text size="sm" c="dimmed">
                {user.account}
                {user.role_name ? ` (${user.role_name})` : ""}
              </Text>
            ) : null}
            <LangSwitcher />
            <Button
              size="xs"
              variant="light"
              loading={isPending}
              onClick={() =>
                logout(undefined, {
                  onSuccess: (result) => {
                    if (!result.success) {
                      return;
                    }
                    // Hard navigation avoids Refine soft go() + invalidateAuthStore
                    // races that refetch /auth/me after the session is cleared.
                    window.location.assign("/login");
                  },
                })
              }
            >
              {t("auth.logout")}
            </Button>
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="sm">
        {navLoading ? <PageLoader /> : null}
        {!navLoading && navError ? (
          <PageError
            message={
              navError === "navigation_load_failed"
                ? t("layout.nav.error")
                : navError
            }
            onRetry={() => void loadNavigation()}
          />
        ) : null}
        {!navLoading && !navError && groups
          ? groups.map((group) => (
              <Stack key={group.id} gap={2} mb="sm">
                <Text size="xs" c="dimmed" tt="uppercase" px="sm" fw={600}>
                  {t(group.label_key)}
                </Text>
                {group.modules.map((module) => (
                  <ConsoleNavLink
                    key={module.id}
                    labelKey={module.label_key}
                    href={module.route}
                    pathname={pathname}
                    onNavigate={() => {
                      if (opened) toggle();
                    }}
                  />
                ))}
              </Stack>
            ))
          : null}
      </AppShell.Navbar>

      <AppShell.Main>{children}</AppShell.Main>
    </AppShell>
  );
}
