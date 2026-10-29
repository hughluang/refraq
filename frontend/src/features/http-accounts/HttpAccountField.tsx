"use client";

import { useEffect, useState } from "react";

import { Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { SelectField } from "@/components/form/SelectField";
import type { FieldNote } from "@/components/form/fieldNotes";
import { getHttpAccount, listHttpAccounts } from "@/features/http-accounts/api";

type HttpAccountOption = { value: string; label: string; auth: string };

function toOption(item: { id: string; name: string; auth: { type: string } }): HttpAccountOption {
  return { value: item.id, label: item.name, auth: item.auth.type };
}

export function HttpAccountField({
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
  const [options, setOptions] = useState<HttpAccountOption[] | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [resolved, setResolved] = useState<{
    value: string;
    option: HttpAccountOption | "missing";
  } | null>(null);
  useEffect(() => {
    let cancelled = false;
    void listHttpAccounts({ limit: 200 })
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
    void getHttpAccount(value)
      .then((body) => {
        if (!cancelled) setResolved({ value, option: toOption(body.http_account) });
      })
      .catch(() => {
        if (!cancelled) setResolved({ value, option: "missing" });
      });
    return () => {
      cancelled = true;
    };
  }, [options, value]);
  const listed = options ?? [];
  const missingLabel = t("channels.config.httpAccount.missing");
  const matched = resolved?.value === value ? resolved.option : null;
  const extra: HttpAccountOption | null =
    !value || listed.some((item) => item.value === value)
      ? null
      : matched === "missing"
        ? { value, label: missingLabel, auth: "" }
        : matched;
  const data = extra ? [extra, ...listed] : listed;
  const known = Boolean(value) && data.some((item) => item.value === value);
  const authLabels = new Map(
    data.map((item) => [
      item.value,
      item.auth ? t(`httpAccounts.auth.${item.auth}`) : "",
    ]),
  );
  return (
    <SelectField
      editable={editable}
      clearable
      label={label}
      description={description}
      notes={notes}
      openSignal={openSignal}
      bare={bare}
      data={data.map((item) => ({ value: item.value, label: item.label }))}
      value={known ? value : null}
      placeholder={t("channels.config.httpAccount.placeholder")}
      error={loadFailed ? t("channels.config.httpAccount.loadFailed") : undefined}
      renderOption={({ option }) => {
        const auth = authLabels.get(option.value);
        return (
          <Stack gap={0}>
            <Text size="sm">{option.label}</Text>
            {auth ? (
              <Text size="xs" c="dimmed">
                {auth}
              </Text>
            ) : null}
          </Stack>
        );
      }}
      onChange={onChange}
    />
  );
}
