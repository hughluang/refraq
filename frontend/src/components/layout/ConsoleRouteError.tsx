"use client";

import { Button, Group, Stack, Text, Title } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { usePathname } from "next/navigation";

import { activeNavigationRoute } from "@/components/layout/consoleNav";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { useModuleIdentityStore } from "@/features/console/module-identity";

type ConsoleRouteErrorProps = {
  reset: () => void;
};

export function ConsoleRouteError({ reset }: ConsoleRouteErrorProps) {
  const t = useTranslate();
  const pathname = usePathname();
  const modules = useModuleIdentityStore((state) => state.modules);
  const listRoutes = modules.flatMap((module) =>
    module.routes.list ? [module.routes.list] : [],
  );
  const listHref = activeNavigationRoute(pathname, listRoutes) ?? "/console";

  return (
    <Stack gap="md" maw={480} py="md">
      <Title order={2} data-page-heading="" tabIndex={-1}>
        {t("layout.error.title")}
      </Title>
      <Text c="dimmed">{t("layout.error.description")}</Text>
      <Group>
        <Button size="sm" onClick={reset}>
          {t("common.retry")}
        </Button>
        <Button component={ConsoleLink} href={listHref} variant="light" size="sm">
          {t("layout.error.moduleList")}
        </Button>
      </Group>
    </Stack>
  );
}
