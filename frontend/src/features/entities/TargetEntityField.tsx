"use client";

import { useTranslate } from "@refinedev/core";
import { useMemo } from "react";

import { RecordPicker } from "@/components/form/RecordPicker";
import type { FieldNote } from "@/components/form/fieldNotes";
import {
  entityRecordAdapter,
  type RecordOption,
  type RecordPickerAdapter,
} from "@/components/form/recordPickerAdapters";
import { REFERENCE_SELF } from "@/features/entities/entityPresentation";

export type TargetSelection = {
  target_entity_id: string;
  target_name: string;
  target_table_name: string;
};

type Props = {
  label: string;
  description?: string;
  required?: boolean;
  error?: string;
  notes?: readonly FieldNote[];
  openSignal?: string | null;
  bare?: boolean;
  value: string;
  selfEntityId: string | null;
  selfName: string;
  selfTableName: string;
  includeSelf?: boolean;
  editable?: boolean;
  cachedName: string;
  cachedTableName: string;
  onChange: (next: TargetSelection) => void;
};

export function TargetEntityField({
  label,
  description,
  required,
  error,
  notes,
  openSignal,
  bare = false,
  value,
  selfEntityId,
  selfName,
  selfTableName,
  includeSelf = true,
  editable = true,
  cachedName,
  cachedTableName,
  onChange,
}: Props) {
  const t = useTranslate();
  const selfValue = selfEntityId ?? REFERENCE_SELF;
  const emptyNameLabel = t("entities.attributes.selfEntity");
  const entities = entityRecordAdapter(["not_serving", "serving"]);
  const selfOption = useMemo<RecordOption>(
    () => ({
      id: selfValue,
      name: selfName.trim() || emptyNameLabel,
      key: selfTableName,
    }),
    [emptyNameLabel, selfName, selfTableName, selfValue],
  );
  const adapter = useMemo<RecordPickerAdapter>(
    () => ({
      async search(q, signal) {
        const items = await entities.search(q, signal);
        const rest = items.filter((item) => item.id !== selfValue);
        if (!includeSelf) return rest;
        const needle = q.trim().toLowerCase();
        const matches =
          needle === "" ||
          selfOption.name.toLowerCase().includes(needle) ||
          selfOption.key.toLowerCase().includes(needle);
        return matches ? [selfOption, ...rest] : rest;
      },
      async resolve(ids, signal) {
        const rest = ids.filter((id) => id !== selfValue);
        const resolved = rest.length > 0 ? await entities.resolve(rest, signal) : [];
        return ids.includes(selfValue) ? [selfOption, ...resolved] : resolved;
      },
    }),
    [entities, includeSelf, selfOption, selfValue],
  );
  const known = useMemo<RecordOption[]>(() => {
    const selected = value.trim();
    if (!selected) return [];
    if (selected === selfValue) return [selfOption];
    if (!cachedName.trim() && !cachedTableName.trim()) return [];
    return [
      {
        id: selected,
        name: cachedName.trim() || selected,
        key: cachedTableName.trim() || selected,
      },
    ];
  }, [cachedName, cachedTableName, selfOption, selfValue, value]);

  return (
    <RecordPicker
      editable={editable}
      required={required}
      label={label}
      description={description}
      notes={notes}
      openSignal={openSignal}
      bare={bare}
      error={error}
      adapter={adapter}
      known={known}
      value={value || null}
      clearable
      onChange={(next, option) => {
        if (!next || !option) {
          onChange({
            target_entity_id: "",
            target_name: "",
            target_table_name: "",
          });
          return;
        }
        if (next === selfValue) {
          onChange({
            target_entity_id: next,
            target_name: "",
            target_table_name: "",
          });
          return;
        }
        onChange({
          target_entity_id: next,
          target_name: option.name,
          target_table_name: option.key,
        });
      }}
    />
  );
}
