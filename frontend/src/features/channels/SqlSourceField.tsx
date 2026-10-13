"use client";

import { useEffect, useState } from "react";

import { useTranslate } from "@refinedev/core";

import { SelectField } from "@/components/form/SelectField";
import type { FieldNote } from "@/components/form/fieldNotes";
import { listSources } from "@/features/sources/api/sources";

const ENTITY = "entity";

type SourceValue = { kind: "entity" } | { kind: "source"; source_id: string };

export function SqlSourceField({
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
  onChange: (value: SourceValue) => void;
}) {
  const t = useTranslate();
  const [options, setOptions] = useState<{ value: string; label: string }[]>([
    { value: ENTITY, label: t("channels.config.sqlSource.entity") },
  ]);
  const [loadFailed, setLoadFailed] = useState(false);

  useEffect(() => {
    let cancelled = false;
    listSources({ limit: 100 })
      .then((page) => {
        if (cancelled) return;
        const sources = page.items.map((source) => ({
          value: source.id,
          label: source.name,
        }));
        setLoadFailed(false);
        setOptions([
          { value: ENTITY, label: t("channels.config.sqlSource.entity") },
          ...sources,
        ]);
      })
      .catch(() => {
        if (!cancelled) setLoadFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [t]);

  const selected = selectedValue(value);
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
      placeholder={t("channels.config.sqlSource.placeholder")}
      error={loadFailed ? t("channels.config.sqlSource.loadFailed") : undefined}
      allowDeselect={false}
      onChange={(next) => {
        if (!next) return;
        if (next === ENTITY) onChange({ kind: "entity" });
        else onChange({ kind: "source", source_id: next });
      }}
    />
  );
}

function selectedValue(value: unknown): string | null {
  if (!value || typeof value !== "object") return null;
  const kind = "kind" in value ? value.kind : null;
  if (kind === "entity") return ENTITY;
  if (kind === "source" && "source_id" in value && typeof value.source_id === "string") {
    return value.source_id;
  }
  return null;
}
