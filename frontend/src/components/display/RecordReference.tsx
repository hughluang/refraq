"use client";

import { Anchor, Button, Group, Text } from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";

import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { copyText } from "@/lib/copy-text";

type Props = {
  /** Human label. Rendered first. */
  name: string;
  /** Key or id. Rendered second, monospace and dimmed. */
  recordKey: string;
  /** Links the name only. The key stays outside the link. */
  href?: string;
  /** Off inside a menu option, where a second click target would steal the choice. */
  copyable?: boolean;
};

export function RecordReference({ name, recordKey, href, copyable = true }: Props) {
  const t = useTranslate();
  const { open } = useNotification();

  async function copyKey() {
    try {
      await copyText(recordKey);
      open?.({ type: "success", message: t("common.copy.success") });
    } catch {
      open?.({ type: "error", message: t("common.copy.failed") });
    }
  }

  const nameNode = href ? (
    <Anchor component={ConsoleLink} href={href} size="sm">
      {name}
    </Anchor>
  ) : (
    <Text size="sm" component="span">
      {name}
    </Text>
  );

  return (
    <Group gap={6} wrap="nowrap" align="baseline">
      {nameNode}
      {copyable ? (
        <Button
          type="button"
          variant="subtle"
          size="compact-xs"
          c="dimmed"
          ff="monospace"
          px={4}
          aria-label={t("recordReference.copy", { value: recordKey })}
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            void copyKey();
          }}
        >
          {recordKey}
        </Button>
      ) : (
        <Text size="xs" c="dimmed" ff="monospace" component="span">
          {recordKey}
        </Text>
      )}
    </Group>
  );
}
