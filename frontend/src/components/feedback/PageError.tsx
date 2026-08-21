"use client";

import { Alert, Button, Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

type PageErrorProps = {
  message: string;
  requestId?: string | null;
  onRetry?: () => void;
};

export function PageError({ message, requestId, onRetry }: PageErrorProps) {
  const t = useTranslate();
  return (
    <Stack gap="sm">
      <Alert color="red" title={t("common.error")}>
        {message}
      </Alert>
      {requestId ? (
        <Text size="xs" c="dimmed">
          {t("common.requestId")}: {requestId}
        </Text>
      ) : null}
      {onRetry ? (
        <Button size="xs" variant="light" onClick={onRetry} w="fit-content">
          {t("common.retry")}
        </Button>
      ) : null}
    </Stack>
  );
}
