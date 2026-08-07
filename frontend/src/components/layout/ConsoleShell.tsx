"use client";

import {
  AppShell,
  Burger,
  Button,
  Group,
  Menu,
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
import { useChangeLanguage } from "next-i18next/client";
import type { ReactNode } from "react";
import { useCallback, useEffect, useState } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";

import { PageError } from "@/components/feedback/PageError";
import { PageLoader } from "@/components/feedback/PageLoader";
import { ConsoleNavLink } from "@/components/layout/ConsoleNavLink";
import { LangSwitcher } from "@/components/LangSwitcher";
import { fetchConsoleNavigation } from "@/features/console/api";
import type { NavigationGroup } from "@/features/console/types";
import { ApiError } from "@/lib/api";
import {
  isLocale,
  LOCALE_COOKIE_NAME,
} from "@/providers/locale-catalog";
import {
  useSessionStore,
  type CurrentUser,
} from "@/providers/session-store";

type ConsoleShellProps = { children: ReactNode };

export function ConsoleShell({ children }: ConsoleShellProps) {
  const t = useTranslate();
  const pathname = usePathname();
  const router = useRouter();
  const [opened, { toggle }] = useDisclosure();
  const { data: user } = useGetIdentity<CurrentUser>();
  const accountLocale = useSessionStore((s) => s.user?.locale);
  const { mutate: logout, isPending } = useLogout();
  const changeLanguage = useChangeLanguage(LOCALE_COOKIE_NAME);
  const { i18n } = useTranslation();
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

  // Apply persisted account locale on identity restore / profile updates.
  // Read from session store (updated by setUser), not Refine identity cache —
  // the latter stays stale across LangSwitcher patches and would race-revert
  // an in-flight changeLanguage when this effect re-runs.
  useEffect(() => {
    if (!accountLocale || !isLocale(accountLocale)) {
      return;
    }
    const current = i18n.resolvedLanguage ?? i18n.language;
    if (current === accountLocale) {
      return;
    }
    void changeLanguage(accountLocale);
    // Only react to account locale changes — not changeLanguage identity churn.
    // eslint-disable-next-line react-hooks/exhaustive-deps -- intentional
  }, [accountLocale]);

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
            <LangSwitcher />
            {user ? (
              <Menu position="bottom-end" withinPortal>
                <Menu.Target>
                  <Button size="xs" variant="subtle">
                    {user.account}
                    {user.role_name ? ` (${user.role_name})` : ""}
                  </Button>
                </Menu.Target>
                <Menu.Dropdown>
                  <Menu.Item onClick={() => router.push("/console/account")}>
                    {t("account.title")}
                  </Menu.Item>
                  <Menu.Divider />
                  <Menu.Item
                    color="red"
                    disabled={isPending}
                    onClick={() =>
                      logout(undefined, {
                        onSuccess: (result) => {
                          if (!result.success) {
                            return;
                          }
                          window.location.assign("/login");
                        },
                      })
                    }
                  >
                    {t("auth.logout")}
                  </Menu.Item>
                </Menu.Dropdown>
              </Menu>
            ) : null}
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
