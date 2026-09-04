"use client";

import { Button, Code, Group, Stack, Text } from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";

import { copyText } from "@/lib/copy-text";

type DdlTabProps = {
  ddl: string | null;
};

export function DdlTab({ ddl }: DdlTabProps) {
  const t = useTranslate();
  const { open } = useNotification();

  if (!ddl) {
    return (
      <Text size="sm" c="dimmed">
        {t("catalog.ddl.empty")}
      </Text>
    );
  }

  const copy = async () => {
    try {
      await copyText(ddl);
      open?.({ type: "success", message: t("common.copy.success") });
    } catch {
      open?.({
        type: "error",
        message: t("common.copy.failed"),
      });
    }
  };

  return (
    <Stack gap="sm">
      <Group>
        <Button size="xs" variant="light" onClick={() => void copy()}>
          {t("catalog.ddl.copy")}
        </Button>
      </Group>
      <Code block style={{ whiteSpace: "pre-wrap" }}>
        {ddl}
      </Code>
    </Stack>
  );
}
