"use client";

import {
  AppShell,
  Burger,
  Button,
  Group,
  Text,
  Title,
} from "@mantine/core";
import { useDisclosure } from "@mantine/hooks";
import {
  useGetIdentity,
  useLogout,
  useMenu,
  useTranslate,
} from "@refinedev/core";
import type { ReactNode } from "react";
import { usePathname } from "next/navigation";

import { AuthorizedNavLink } from "@/components/layout/AuthorizedNavLink";
import { LangSwitcher } from "@/components/LangSwitcher";
import type { CurrentUser } from "@/providers/session-store";

type ConsoleShellProps = { children: ReactNode };

export function ConsoleShell({ children }: ConsoleShellProps) {
  const t = useTranslate();
  const pathname = usePathname();
  const [opened, { toggle }] = useDisclosure();
  const { data: user } = useGetIdentity<CurrentUser>();
  const { mutate: logout, isPending } = useLogout();
  const { menuItems } = useMenu();

  const navigableMenuItems = menuItems.filter((item) => item.route);

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
        {navigableMenuItems.map((item) => (
          <AuthorizedNavLink
            key={item.key}
            item={item}
            pathname={pathname}
            onNavigate={() => {
              if (opened) toggle();
            }}
          />
        ))}
      </AppShell.Navbar>

      <AppShell.Main>{children}</AppShell.Main>
    </AppShell>
  );
}
