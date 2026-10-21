"use client";

import { useEffect, useState } from "react";

import { Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { SelectField } from "@/components/form/SelectField";
import type { FieldNote } from "@/components/form/fieldNotes";
import { getEmailAccount, listEmailAccounts } from "@/features/email-accounts/api";

type EmailAccountOption = { value: string; label: string; host: string };

function toOption(item: { id: string; name: string; host: string }): EmailAccountOption {
  return { value: item.id, label: item.name, host: item.host };
}

export function EmailAccountField({
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
  const [options, setOptions] = useState<EmailAccountOption[] | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [resolved, setResolved] = useState<{
    value: string;
    option: EmailAccountOption | "missing";
  } | null>(null);
  useEffect(() => {
    let cancelled = false;
    void listEmailAccounts({ limit: 200 })
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
    void getEmailAccount(value)
      .then((body) => {
        if (!cancelled) setResolved({ value, option: toOption(body.email_account) });
      })
      .catch(() => {
        if (!cancelled) setResolved({ value, option: "missing" });
      });
    return () => {
      cancelled = true;
    };
  }, [options, value]);
  const listed = options ?? [];
  const missingLabel = t("channels.config.emailAccount.missing");
  const matched = resolved?.value === value ? resolved.option : null;
  const extra: EmailAccountOption | null =
    !value || listed.some((item) => item.value === value)
      ? null
      : matched === "missing"
        ? { value, label: missingLabel, host: "" }
        : matched;
  const data =
    extra && !listed.some((item) => item.value === extra.value) ? [extra, ...listed] : listed;
  const known = Boolean(value) && data.some((item) => item.value === value);
  const hosts = new Map(data.map((item) => [item.value, item.host]));
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
      placeholder={t("channels.config.emailAccount.placeholder")}
      error={loadFailed ? t("channels.config.emailAccount.loadFailed") : undefined}
      renderOption={({ option }) => {
        const host = hosts.get(option.value);
        return (
          <Stack gap={0}>
            <Text size="sm">{option.label}</Text>
            {host ? (
              <Text size="xs" c="dimmed">
                {host}
              </Text>
            ) : null}
          </Stack>
        );
      }}
      onChange={(next) => onChange(next ?? "")}
    />
  );
}
