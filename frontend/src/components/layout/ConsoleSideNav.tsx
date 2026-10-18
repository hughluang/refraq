"use client";

import { Divider, NavLink, Stack, Text, Tooltip } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { moduleIcon } from "@/components/icons";
import { activeNavigationRoute } from "@/components/layout/consoleNav";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import type { NavigationGroup } from "@/features/console/types";

type ConsoleSideNavProps = {
  groups: NavigationGroup[];
  pathname: string;
  rail: boolean;
  iconFor: (moduleId: string) => string | null;
  onNavigate?: () => void;
};

export function ConsoleSideNav({
  groups,
  pathname,
  rail,
  iconFor,
  onNavigate,
}: ConsoleSideNavProps) {
  const t = useTranslate();
  const active = activeNavigationRoute(
    pathname,
    groups.flatMap((group) => group.modules.map((module) => module.route)),
  );

  return (
    <>
      {groups.map((group, index) => (
        <Stack key={group.id} gap={2} mb="sm">
          {rail ? (
            index > 0 ? <Divider /> : null
          ) : (
            <Text size="xs" c="dimmed" tt="uppercase" px="sm" fw={600}>
              {t(group.label_key)}
            </Text>
          )}
          {group.modules.map((module) => {
            const label = t(module.label_key);
            const current = module.route === active;
            const Icon = moduleIcon(iconFor(module.id));
            return (
              <Tooltip
                key={module.id}
                label={label}
                position="right"
                disabled={!rail}
              >
                <NavLink
                  component={ConsoleLink}
                  href={module.route}
                  label={rail ? undefined : label}
                  aria-label={label}
                  aria-current={current ? "page" : undefined}
                  active={current}
                  leftSection={<Icon />}
                  onClick={onNavigate}
                />
              </Tooltip>
            );
          })}
        </Stack>
      ))}
    </>
  );
}
