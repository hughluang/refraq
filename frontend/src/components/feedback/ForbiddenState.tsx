"use client";

import { Button, Group, Stack, Text, Title } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import Link from "next/link";

const PERMISSION_KEY = /^[a-z][a-z0-9_]*:[a-z][a-z0-9_]*$/i;

type ForbiddenStateProps = {
  reason?: string;
};

export function ForbiddenState({ reason }: ForbiddenStateProps) {
  const t = useTranslate();
  const unregistered = reason === "unregistered_route";
  const requiredPermission =
    reason && PERMISSION_KEY.test(reason) ? reason : undefined;

  return (
    <Stack gap="md" maw={480} py="md">
      <Title order={2}>
        {t(unregistered ? "forbidden.unregistered.title" : "forbidden.title")}
      </Title>
      <Text c="dimmed">
        {t(
          unregistered
            ? "forbidden.unregistered.description"
            : "forbidden.description",
        )}
      </Text>
      {requiredPermission ? (
        <Text size="sm">
          {t("forbidden.requiredPermission", {
            permission: requiredPermission,
          })}
        </Text>
      ) : null}
      <Group>
        <Button component={Link} href="/console" variant="light">
          {t("forbidden.back")}
        </Button>
      </Group>
    </Stack>
  );
}
