"use client";

import { useTranslate } from "@refinedev/core";

import { SelectField } from "@/components/form/SelectField";
import type { FieldNote } from "@/components/form/fieldNotes";
import {
  sourceSelectData,
  useSourceDisplay,
  useSourceOptions,
} from "@/features/channels/RegisteredSourceField";

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
  const { options: sources, loadFailed, loaded } = useSourceOptions();
  const selected = selectedValue(value);
  const sourceId = selected !== null && selected !== ENTITY ? selected : null;
  const display = useSourceDisplay(sourceId);
  const listed = sourceSelectData(
    sources,
    sourceId,
    display,
    t("channels.config.source.inaccessible"),
    loaded,
  );
  const data = [{ value: ENTITY, label: t("channels.config.sqlSource.entity") }, ...listed];

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
