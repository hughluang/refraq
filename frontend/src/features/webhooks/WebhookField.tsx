"use client";

import { useEffect, useState } from "react";

import { Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { SelectField } from "@/components/form/SelectField";
import type { FieldNote } from "@/components/form/fieldNotes";
import { getWebhook, listWebhooks } from "@/features/webhooks/api";

type WebhookOption = { value: string; label: string; url: string };

function toOption(item: { id: string; name: string; url: string }): WebhookOption {
  return { value: item.id, label: item.name, url: item.url };
}

export function WebhookField({
  label,
  description,
  value,
  editable,
  notes,
  openSignal,
  bare,
  onChange,
}: {
  label: string;
  description?: string;
  value: string;
  editable: boolean;
  notes?: readonly FieldNote[];
  openSignal?: string | null;
  bare?: boolean;
  onChange: (value: unknown) => void;
}) {
  const t = useTranslate();
  const [options, setOptions] = useState<WebhookOption[] | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [resolved, setResolved] = useState<{
    value: string;
    option: WebhookOption | "missing";
  } | null>(null);
  useEffect(() => {
    let cancelled = false;
    void listWebhooks({ limit: 200 })
      .then((page) => {
        if (cancelled) return;
        setLoadFailed(false);
        setOptions(page.items.map(toOption));
      })
      .catch(() => {
        if (cancelled) return;
        setLoadFailed(true);
        setOptions([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  useEffect(() => {
    if (!value || options == null || options.some((item) => item.value === value)) {
      return;
    }
    let cancelled = false;
    void getWebhook(value)
      .then((body) => {
        if (!cancelled) setResolved({ value, option: toOption(body.webhook) });
      })
      .catch(() => {
        if (!cancelled) setResolved({ value, option: "missing" });
      });
    return () => {
      cancelled = true;
    };
  }, [options, value]);
  const listed = options ?? [];
  const missingLabel = t("channels.config.webhook.missing");
  const matched = resolved?.value === value ? resolved.option : null;
  const extra: WebhookOption | null =
    !value || listed.some((item) => item.value === value)
      ? null
      : matched === "missing"
        ? { value, label: missingLabel, url: "" }
        : matched;
  const data =
    extra && !listed.some((item) => item.value === extra.value) ? [extra, ...listed] : listed;
  const known = Boolean(value) && data.some((item) => item.value === value);
  const urls = new Map(data.map((item) => [item.value, item.url]));
  return (
    <SelectField
      editable={editable}
      label={label}
      description={description}
      notes={notes}
      openSignal={openSignal}
      bare={bare}
      data={data.map((item) => ({ value: item.value, label: item.label }))}
      value={known ? value : null}
      placeholder={t("channels.config.webhook.placeholder")}
      error={loadFailed ? t("channels.config.webhook.loadFailed") : undefined}
      renderOption={({ option }) => {
        const url = urls.get(option.value);
        return (
          <Stack gap={0}>
            <Text size="sm">{option.label}</Text>
            {url ? (
              <Text size="xs" c="dimmed">
                {url}
              </Text>
            ) : null}
          </Stack>
        );
      }}
      onChange={(next) => onChange(next ?? "")}
    />
  );
}
