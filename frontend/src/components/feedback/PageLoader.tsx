"use client";

import { Center, Loader, Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

export function PageLoader() {
  const t = useTranslate();
  return (
    <Center mih={200} p="md">
      <Stack align="center" gap="sm">
        <Loader size="sm" />
        <Text size="sm" c="dimmed">
          {t("common.loading")}
        </Text>
      </Stack>
    </Center>
  );
}
