"use client";

import { useEffect, useState } from "react";

import { useTranslate } from "@refinedev/core";

import { SelectField } from "@/components/form/SelectField";
import type { FieldNote } from "@/components/form/fieldNotes";
import { listSources } from "@/features/sources/api/sources";

export function RegisteredSourceField({
  label,
  description,
  value,
  editable,
  notes,
  openSignal,
  bare = false,
  onChange,
}: {
  label: string;
  description: string;
  value: unknown;
  editable: boolean;
  notes?: readonly FieldNote[];
  openSignal?: string | null;
  bare?: boolean;
  onChange: (value: string) => void;
}) {
  const t = useTranslate();
  const { options, loadFailed } = useSourceOptions();

  const selected = typeof value === "string" && value !== "" ? value : null;
  const data = options.some((option) => option.value === selected)
    ? options
    : selected
      ? [...options, { value: selected, label: selected }]
      : options;

  return (
    <SelectField
      editable={editable}
      label={label}
      description={description}
      notes={notes}
      openSignal={openSignal}
      bare={bare}
      data={data}
      value={selected}
      placeholder={t("channels.config.source.placeholder")}
      error={loadFailed ? t("channels.config.source.loadFailed") : undefined}
      allowDeselect={false}
      onChange={(next) => {
        if (next) onChange(next);
      }}
    />
  );
}

export type SourceOption = { value: string; label: string };

export function useSourceOptions(): { options: SourceOption[]; loadFailed: boolean } {
  const [options, setOptions] = useState<SourceOption[]>([]);
  const [loadFailed, setLoadFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    listSources({ limit: 100 })
      .then((page) => {
        if (cancelled) return;
        setLoadFailed(false);
        setOptions(page.items.map((source) => ({ value: source.id, label: source.name })));
      })
      .catch(() => {
        if (!cancelled) setLoadFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return { options, loadFailed };
}
