"use client";

import { Button, Center, Group, Paper, Stack, Text, Title } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import Link from "next/link";

export default function ForbiddenPage() {
  const t = useTranslate();

  return (
    <Center mih="100vh" p="md">
      <Paper p="xl" withBorder w={420}>
        <Stack gap="md">
          <Title order={3}>{t("forbidden.title")}</Title>
          <Text c="dimmed">{t("forbidden.description")}</Text>
          <Group justify="flex-end">
            <Button component={Link} href="/console" variant="light">
              {t("forbidden.back")}
            </Button>
          </Group>
        </Stack>
      </Paper>
    </Center>
  );
}
