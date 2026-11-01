"use client";

import { useEffect, useState } from "react";

import { Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { SelectField } from "@/components/form/SelectField";
import type { FieldNote } from "@/components/form/fieldNotes";
import {
  getInboundCredential,
  listInboundCredentials,
} from "@/features/inbound-credentials/api";

type InboundCredentialOption = { value: string; label: string; type: string };

function toOption(item: { id: string; name: string; type: string }): InboundCredentialOption {
  return { value: item.id, label: item.name, type: item.type };
}

export function InboundCredentialField({
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
  const [options, setOptions] = useState<InboundCredentialOption[] | null>(null);
  const [loadFailed, setLoadFailed] = useState(false);
  const [resolved, setResolved] = useState<{
    value: string;
    option: InboundCredentialOption | "missing";
  } | null>(null);
  useEffect(() => {
    let cancelled = false;
    void listInboundCredentials({ limit: 200 })
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
    void getInboundCredential(value)
      .then((body) => {
        if (!cancelled) setResolved({ value, option: toOption(body.inbound_credential) });
      })
      .catch(() => {
        if (!cancelled) setResolved({ value, option: "missing" });
      });
    return () => {
      cancelled = true;
    };
  }, [options, value]);
  const listed = options ?? [];
  const missingLabel = t("inboundCredentials.picker.missing");
  const matched = resolved?.value === value ? resolved.option : null;
  const extra: InboundCredentialOption | null =
    !value || listed.some((item) => item.value === value)
      ? null
      : matched === "missing"
        ? { value, label: missingLabel, type: "" }
        : matched;
  const data = extra ? [extra, ...listed] : listed;
  const known = Boolean(value) && data.some((item) => item.value === value);
  const typeLabels = new Map(
    data.map((item) => [
      item.value,
      item.type ? t(`inboundCredentials.types.${item.type}`) : "",
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
      placeholder={t("inboundCredentials.picker.placeholder")}
      error={loadFailed ? t("inboundCredentials.picker.loadFailed") : undefined}
      renderOption={({ option }) => {
        const type = typeLabels.get(option.value);
        return (
          <Stack gap={0}>
            <Text size="sm">{option.label}</Text>
            {type ? (
              <Text size="xs" c="dimmed">
                {type}
              </Text>
            ) : null}
          </Stack>
        );
      }}
      onChange={onChange}
    />
  );
}
