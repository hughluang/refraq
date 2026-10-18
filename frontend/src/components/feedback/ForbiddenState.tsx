"use client";

import { Button, Group, Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { usePathname } from "next/navigation";

import { moduleForPermission } from "@/components/feedback/forbiddenModule";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { useModuleIdentityStore } from "@/features/console/module-identity";

type ForbiddenStateProps = {
  reason?: string;
};

export function ForbiddenState({ reason }: ForbiddenStateProps) {
  const t = useTranslate();
  const pathname = usePathname();
  const modules = useModuleIdentityStore((state) => state.modules);
  const module = moduleForPermission(modules, reason, pathname);
  const label = module ? t(module.label_key) : "";
  const named = Boolean(module && label && label !== reason);
  const sentence = named
    ? t("forbidden.module", { module: label })
    : t("forbidden.description");

  return (
    <Stack gap="md" maw={480} py="md">
      <Text>{sentence}</Text>
      <Group>
        <Button component={ConsoleLink} href="/console" variant="light">
          {t("forbidden.back")}
        </Button>
      </Group>
    </Stack>
  );
}
