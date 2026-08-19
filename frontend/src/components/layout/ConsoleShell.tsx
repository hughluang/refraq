"use client";

import {
  AppShell,
  Burger,
  Button,
  Group,
  Menu,
  Skeleton,
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

import { ForbiddenState } from "@/components/feedback/ForbiddenState";
import { PageError } from "@/components/feedback/PageError";
import { ConsoleNavLink } from "@/components/layout/ConsoleNavLink";
import { LangSwitcher } from "@/components/LangSwitcher";
import { fetchConsoleNavigation } from "@/features/console/api";
import type { NavigationGroup } from "@/features/console/types";
import { ApiError } from "@/lib/api";
import { reloadIdentity } from "@/providers/auth-provider";
import {
  isLocale,
  LOCALE_COOKIE_NAME,
} from "@/providers/locale-catalog";
import {
  useSessionStore,
  type CurrentUser,
} from "@/providers/session-store";

type ConsoleShellProps = { children: ReactNode };

type NavErrorKind = "forbidden" | "failed";

function NavSkeleton() {
  return (
    <Stack gap="sm" px="sm">
      <Skeleton height={10} width="40%" />
      <Skeleton height={28} radius="sm" />
      <Skeleton height={28} radius="sm" />
      <Skeleton height={10} width="35%" mt="sm" />
      <Skeleton height={28} radius="sm" />
      <Skeleton height={28} radius="sm" />
    </Stack>
  );
}

export function ConsoleShell({ children }: ConsoleShellProps) {
  const t = useTranslate();
  const pathname = usePathname();
  const router = useRouter();
  const [opened, { toggle }] = useDisclosure();
  const { data: identity } = useGetIdentity<CurrentUser>();
  const sessionUser = useSessionStore((s) => s.user);
  const identityError = useSessionStore((s) => s.identityError);
  const permissionsReady = useSessionStore((s) => s.permissionsReady);
  const user = identity ?? sessionUser;
  const accountLocale = useSessionStore((s) => s.user?.locale);
  const { mutate: logout, isPending } = useLogout();
  const changeLanguage = useChangeLanguage(LOCALE_COOKIE_NAME);
  const { i18n } = useTranslation();
  const [groups, setGroups] = useState<NavigationGroup[] | null>(null);
  const [navError, setNavError] = useState<string | null>(null);
  const [navErrorKind, setNavErrorKind] = useState<NavErrorKind | null>(null);
  const [navLoading, setNavLoading] = useState(true);

  const loadNavigation = useCallback(async () => {
    setNavLoading(true);
    setNavError(null);
    setNavErrorKind(null);
    try {
      const data = await fetchConsoleNavigation();
      setGroups(data.groups);
    } catch (error) {
      setGroups(null);
      const forbidden =
        error instanceof ApiError &&
        error.status === 403;
      setNavErrorKind(forbidden ? "forbidden" : "failed");
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

  const mainContent =
    !navLoading && navErrorKind === "forbidden" ? (
      <ForbiddenState reason="console:access" />
    ) : identityError && !permissionsReady ? (
      <PageError
        message={
          identityError === "identity_load_failed"
            ? t("common.error.loadFailed")
            : identityError
        }
        onRetry={() => void reloadIdentity()}
      />
    ) : (
      children
    );

  return (
    <AppShell
      header={{ height: 56 }}
      navbar={{
        width: 220,
        breakpoint: "sm",
        collapsed: { mobile: !opened },
      }}
      padding="md"
      h="100dvh"
      style={{ overflow: "hidden" }}
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
            ) : (
              <Skeleton height={28} width={96} radius="sm" />
            )}
          </Group>
        </Group>
      </AppShell.Header>

      <AppShell.Navbar p="sm">
        {navLoading ? <NavSkeleton /> : null}
        {!navLoading && navError && navErrorKind !== "forbidden" ? (
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

      <AppShell.Main
        display="flex"
        h="100dvh"
        mih={0}
        style={{ flexDirection: "column", overflow: "hidden" }}
      >
        {mainContent}
      </AppShell.Main>
    </AppShell>
  );
}
