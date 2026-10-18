"use client";

import {
  AppShell,
  Anchor,
  Burger,
  Button,
  Group,
  Menu,
  Modal,
  Skeleton,
  Stack,
  Text,
  Title,
  Tooltip,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import { NavigationProgress } from "@mantine/nprogress";
import {
  useGetIdentity,
  useLogout,
  useTranslate,
} from "@refinedev/core";
import { useChangeLanguage } from "next-i18next/client";
import type { ReactNode } from "react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { usePathname } from "next/navigation";
import { useTranslation } from "react-i18next";

import { ColorSchemeControl } from "@/components/ColorSchemeControl";
import { BrandMark } from "@/components/display/BrandMark";
import { ForbiddenState } from "@/components/feedback/ForbiddenState";
import { PageError } from "@/components/feedback/PageError";
import { NavCollapseIcon, NavExpandIcon } from "@/components/icons";
import { CommandPalette } from "@/components/layout/CommandPalette";
import { ConsolePaletteTrigger } from "@/components/layout/ConsolePaletteTrigger";
import { ConsoleNavDataProvider } from "@/components/layout/consoleNavData";
import { ConsoleSideNav } from "@/components/layout/ConsoleSideNav";
import { ConsoleSkipLink } from "@/components/layout/ConsoleSkipLink";
import {
  CONSOLE_MAIN_ID,
  NAV_EXPANDED_WIDTH,
  NAV_RAIL_WIDTH,
} from "@/components/layout/consoleNav";
import {
  useNavMode,
  useNavOverlay,
  usePageHeadingFocus,
} from "@/components/layout/useConsoleChrome";
import { LangSwitcher } from "@/components/LangSwitcher";
import { confirmLeave } from "@/components/navigation/leaveGuard";
import { useNavigationProgress } from "@/components/layout/useNavigationProgress";
import { useConsoleNavigation } from "@/components/navigation/useConsoleNavigation";
import { fetchConsoleNavigation } from "@/features/console/api";
import { useModuleIdentityStore } from "@/features/console/module-identity";
import type { NavigationGroup } from "@/features/console/types";
import { useBranding } from "@/features/branding/BrandingProvider";
import { ApiError, isSessionExpiredError } from "@/lib/api";
import { problemMessage } from "@/lib/problem";
import { translateKey } from "@/providers/i18n-runtime";
import { reloadIdentity } from "@/providers/auth-provider";
import {
  isLocale,
  LOCALE_COOKIE_NAME,
} from "@/providers/locale-catalog";
import {
  useSessionStore,
  type CurrentUser,
} from "@/providers/session-store";

import "./ConsoleShell.css";

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

function NavWidthToggle({
  rail,
  onToggle,
}: {
  rail: boolean;
  onToggle: () => void;
}) {
  const t = useTranslate();
  const label = rail ? t("layout.nav.expand") : t("layout.nav.collapse");
  return (
    <Tooltip label={label} position="right" disabled={!rail}>
      <Button
        variant="subtle"
        size="compact-sm"
        fullWidth
        justify={rail ? "center" : "flex-start"}
        aria-label={label}
        aria-pressed={rail}
        leftSection={rail ? <NavExpandIcon /> : <NavCollapseIcon />}
        onClick={onToggle}
      >
        {rail ? null : label}
      </Button>
    </Tooltip>
  );
}

export function ConsoleShell({ children }: ConsoleShellProps) {
  const t = useTranslate();
  const pathname = usePathname();
  const { push } = useConsoleNavigation();
  const { rail, toggle: toggleRail } = useNavMode();
  const overlay = useNavOverlay(pathname);
  usePageHeadingFocus(pathname);
  useNavigationProgress();
  const [aboutOpened, { open: openAbout, close: closeAbout }] = useDisclosure();
  const branding = useBranding();
  const { data: identity } = useGetIdentity<CurrentUser>();
  const sessionUser = useSessionStore((s) => s.user);
  const identityError = useSessionStore((s) => s.identityError);
  const permissionsReady = useSessionStore((s) => s.permissionsReady);
  const identityModules = useModuleIdentityStore((state) => state.modules);
  const user = identity ?? sessionUser;
  const accountLocale = useSessionStore((s) => s.user?.locale);
  const { mutate: logout, isPending } = useLogout();
  const changeLanguage = useChangeLanguage(LOCALE_COOKIE_NAME);
  const { i18n } = useTranslation();
  const [groups, setGroups] = useState<NavigationGroup[] | null>(null);
  const [navError, setNavError] = useState<string | null>(null);
  const [navErrorKind, setNavErrorKind] = useState<NavErrorKind | null>(null);
  const [navLoading, setNavLoading] = useState(true);

  const iconFor = useMemo(() => {
    const icons = new Map<string, string | null>();
    for (const module of identityModules) {
      icons.set(module.id, module.icon ?? null);
    }
    return (moduleId: string) => icons.get(moduleId) ?? null;
  }, [identityModules]);

  const loadNavigation = useCallback(async () => {
    setNavLoading(true);
    setNavError(null);
    setNavErrorKind(null);
    try {
      const data = await fetchConsoleNavigation();
      setGroups(data.groups);
    } catch (error) {
      if (isSessionExpiredError(error)) {
        setNavLoading(false);
        return;
      }
      setGroups(null);
      const forbidden =
        error instanceof ApiError &&
        error.status === 403;
      setNavErrorKind(forbidden ? "forbidden" : "failed");
      setNavError(
        problemMessage(translateKey, error, "navigation_load_failed"),
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
    <ConsoleNavDataProvider
      groups={groups ?? []}
      ready={!navLoading}
      toggleNavigation={toggleRail}
    >
    <AppShell
      header={{ height: 56 }}
      navbar={{
        width: rail ? NAV_RAIL_WIDTH : NAV_EXPANDED_WIDTH,
        breakpoint: "sm",
        collapsed: { mobile: !overlay.opened },
      }}
      padding="md"
      h="100dvh"
      style={{ overflow: "hidden" }}
    >
      <NavigationProgress aria-label={t("common.loading")} />
      <CommandPalette />
      <ConsoleSkipLink />
      <AppShell.Header>
        <Group h="100%" px="md" justify="space-between" wrap="nowrap">
          <Group gap="sm" wrap="nowrap">
            <Burger
              ref={overlay.menuRef}
              opened={overlay.opened}
              onClick={overlay.toggle}
              hiddenFrom="sm"
              size="sm"
              aria-label={t("layout.nav.label")}
            />
            {branding.logoUrl ? (
              <BrandMark src={branding.logoUrl} alt={branding.brandName} height={28} />
            ) : null}
            {branding.raw.show_brand_name_with_logo ? (
              <Title order={4}>{branding.brandName}</Title>
            ) : null}
          </Group>
          <Group gap="sm" wrap="nowrap">
            <ConsolePaletteTrigger />
            <ColorSchemeControl />
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
                  <Menu.Item onClick={() => push("/console/account")}>
                    {t("account.title")}
                  </Menu.Item>
                  <Menu.Item onClick={openAbout}>
                    {t("branding.about")}
                  </Menu.Item>
                  <Menu.Divider />
                  <Menu.Item
                    color="red"
                    disabled={isPending}
                    onClick={() => {
                      void confirmLeave().then((allowed) => {
                        if (!allowed) return;
                        logout(undefined, {
                          onSuccess: (result) => {
                            if (!result.success) {
                              return;
                            }
                            window.location.assign("/login");
                          },
                        });
                      });
                    }}
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

      <AppShell.Navbar className="console-navbar" p={0}>
        <AppShell.Section
          grow
          p="sm"
          style={{ overflowY: "auto" }}
          component="nav"
          aria-label={t("layout.nav.label")}
        >
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
          {!navLoading && !navError && groups ? (
            <ConsoleSideNav
              groups={groups}
              pathname={pathname}
              rail={rail}
              iconFor={iconFor}
              onNavigate={() => {
                if (overlay.opened) overlay.close();
              }}
            />
          ) : null}
        </AppShell.Section>
        <AppShell.Section
          p="sm"
          style={{ borderTop: "1px solid var(--mantine-color-default-border)" }}
        >
          <NavWidthToggle rail={rail} onToggle={toggleRail} />
        </AppShell.Section>
      </AppShell.Navbar>

      <AppShell.Main
        id={CONSOLE_MAIN_ID}
        tabIndex={-1}
        display="flex"
        h="100dvh"
        mih={0}
        style={{ flexDirection: "column", overflow: "hidden" }}
      >
        {mainContent}
      </AppShell.Main>
      <Modal
        opened={aboutOpened}
        onClose={closeAbout}
        title={t("branding.about")}
        centered
      >
        <Text size="sm">
          Refraq
        </Text>
        <Anchor
          href="https://github.com/hughluang/refraq"
          target="_blank"
          rel="noreferrer"
          size="sm"
        >
          github.com/hughluang/refraq
        </Anchor>
      </Modal>
    </AppShell>
    </ConsoleNavDataProvider>
  );
}
