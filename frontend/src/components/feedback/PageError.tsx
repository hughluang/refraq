"use client";

import { Alert, Button, Stack } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

type PageErrorProps = {
  message: string;
  onRetry?: () => void;
};

export function PageError({ message, onRetry }: PageErrorProps) {
  const t = useTranslate();
  return (
    <Stack gap="sm">
      <Alert color="red" title={t("common.error")}>
        {message}
      </Alert>
      {onRetry ? (
        <Button size="xs" variant="light" onClick={onRetry} w="fit-content">
          {t("common.retry")}
        </Button>
      ) : null}
    </Stack>
  );
}
