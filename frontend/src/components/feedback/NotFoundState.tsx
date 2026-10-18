"use client";

import { Button, Group, Stack, Text, Title } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { ConsoleLink } from "@/components/navigation/ConsoleLink";

export function NotFoundState() {
  const t = useTranslate();
  return (
    <Stack gap="md" maw={480} py="md">
      <Title order={2} data-page-heading="" tabIndex={-1}>
        {t("layout.notFound.title")}
      </Title>
      <Text c="dimmed">{t("layout.notFound.description")}</Text>
      <Group>
        <Button component={ConsoleLink} href="/console" variant="light">
          {t("layout.notFound.home")}
        </Button>
      </Group>
    </Stack>
  );
}
