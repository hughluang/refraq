"use client";

import { Anchor, Group, Paper, SimpleGrid, Stack, Text, Title } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useState } from "react";

import { moduleIcon } from "@/components/icons";
import { PageChrome } from "@/components/layout/PageChrome";
import { useConsoleNavData } from "@/components/layout/consoleNavData";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { useBranding } from "@/features/branding/BrandingProvider";
import { useModuleIdentityStore } from "@/features/console/module-identity";
import { readRecents, subscribeRecents, type RecentVisit } from "@/lib/recents";
import { useSessionStore } from "@/providers/session-store";

function useHomeRecents(userId: string | undefined): RecentVisit[] {
  const [items, setItems] = useState<RecentVisit[]>(() =>
    userId ? readRecents(userId) : [],
  );
  useEffect(() => {
    setItems(userId ? readRecents(userId) : []);
    if (!userId) return;
    return subscribeRecents(() => setItems(readRecents(userId)));
  }, [userId]);
  return items;
}

export default function ConsoleHomePage() {
  const t = useTranslate();
  const branding = useBranding();
  const userId = useSessionStore((state) => state.user?.id);
  const recents = useHomeRecents(userId);
  const { groups, ready } = useConsoleNavData();
  const identities = useModuleIdentityStore((state) => state.modules);

  function iconFor(moduleId: string) {
    return moduleIcon(identities.find((module) => module.id === moduleId)?.icon);
  }

  function moduleLabel(moduleId: string): string {
    const identity = identities.find((module) => module.id === moduleId);
    return identity ? t(identity.label_key) : "";
  }

  return (
    <PageChrome
      title={branding.brandName}
      description={t("dashboard.description")}
      status={ready ? "ready" : "loading"}
    >
      <Stack gap="xl">
        {recents.length > 0 ? (
          <Stack gap="sm">
            <Title order={2}>{t("home.recents")}</Title>
            <Stack gap="xs">
              {recents.map((item) => {
                const Icon = iconFor(item.moduleId);
                return (
                  <Anchor
                    key={item.href}
                    component={ConsoleLink}
                    href={item.href}
                    underline="never"
                    c="inherit"
                  >
                    <Group gap="sm" wrap="nowrap">
                      <Icon />
                      <Text>{item.title}</Text>
                      <Text size="sm" c="dimmed">
                        {moduleLabel(item.moduleId)}
                      </Text>
                    </Group>
                  </Anchor>
                );
              })}
            </Stack>
          </Stack>
        ) : null}
        {groups.length > 0 ? (
          <Stack gap="lg">
            <Title order={2}>{t("home.modules")}</Title>
            {groups.map((group) => (
              <Stack key={group.id} gap="sm">
                <Text size="xs" c="dimmed" tt="uppercase" fw={600}>
                  {t(group.label_key)}
                </Text>
                <SimpleGrid cols={{ base: 1, xs: 2, md: 3 }}>
                  {group.modules.map((module) => {
                    const Icon = iconFor(module.id);
                    const label = t(module.label_key);
                    return (
                      <Paper key={module.id} withBorder p="sm" radius="sm">
                        <Anchor
                          component={ConsoleLink}
                          href={module.route}
                          underline="never"
                          c="inherit"
                        >
                          <Group gap="sm" wrap="nowrap">
                            <Icon />
                            <Text>{label}</Text>
                          </Group>
                        </Anchor>
                      </Paper>
                    );
                  })}
                </SimpleGrid>
              </Stack>
            ))}
          </Stack>
        ) : null}
      </Stack>
    </PageChrome>
  );
}
