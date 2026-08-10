"use client";

import { Button, Code, Group, Stack, Text } from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";

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
      await navigator.clipboard.writeText(ddl);
      open?.({ type: "success", message: t("catalog.copied") });
    } catch (err) {
      open?.({
        type: "error",
        message: err instanceof Error ? err.message : String(err),
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
