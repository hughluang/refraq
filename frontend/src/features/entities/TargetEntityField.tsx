"use client";

import { useTranslate } from "@refinedev/core";
import { useEffect, useMemo, useState } from "react";

import { SelectField } from "@/components/form/SelectField";
import type { FieldNote } from "@/components/form/fieldNotes";
import { listEntities } from "@/features/entities/api";
import {
  REFERENCE_SELF,
  referenceOptionLabel,
  referenceSummaryLabel,
} from "@/features/entities/entityPresentation";
import type { BusinessEntity } from "@/features/entities/types";
import { useSearchDebounce } from "@/hooks/useSearchDebounce";

const PAGE_LIMIT = 50;

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

function queryMatches(query: string, ...parts: string[]): boolean {
  const needle = query.trim().toLowerCase();
  if (!needle) return true;
  return parts.some((part) => part.toLowerCase().includes(needle));
}

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
  const [search, setSearch] = useState("");
  const debouncedSearch = useSearchDebounce(search);
  const [entities, setEntities] = useState<BusinessEntity[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadFailed, setLoadFailed] = useState(false);
  const selfValue = selfEntityId ?? REFERENCE_SELF;
  const emptyNameLabel = t("entities.attributes.selfEntity");

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setLoadFailed(false);
    void listEntities({
      q: debouncedSearch.trim() || undefined,
      status: ["not_serving", "serving"],
      limit: PAGE_LIMIT,
    })
      .then((page) => {
        if (cancelled) return;
        setEntities(page.items);
        setLoadFailed(false);
      })
      .catch(() => {
        if (cancelled) return;
        setEntities([]);
        setLoadFailed(true);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [debouncedSearch]);

  const data = useMemo(() => {
    const options: { value: string; label: string }[] = [];
    if (includeSelf && queryMatches(debouncedSearch, selfName, selfTableName)) {
      options.push({
        value: selfValue,
        label: referenceOptionLabel({
          name: selfName,
          tableName: selfTableName,
          emptyNameLabel,
        }),
      });
    }
    for (const entity of entities) {
      if (entity.id === selfValue) continue;
      options.push({
        value: entity.id,
        label: referenceOptionLabel({
          name: entity.name,
          tableName: entity.table_name,
          emptyNameLabel,
        }),
      });
    }
    const selected = value.trim();
    if (selected && !options.some((option) => option.value === selected)) {
      options.unshift({
        value: selected,
        label:
          referenceSummaryLabel({
            targetEntityId: selected,
            selfEntityId,
            selfName,
            selfTableName,
            cachedName,
            cachedTableName,
            emptyNameLabel,
          }) ?? selected,
      });
    }
    return options;
  }, [
    cachedName,
    cachedTableName,
    debouncedSearch,
    emptyNameLabel,
    entities,
    includeSelf,
    selfEntityId,
    selfName,
    selfTableName,
    selfValue,
    value,
  ]);

  return (
    <SelectField
      editable={editable}
      required={required}
      label={label}
      description={description}
      notes={notes}
      openSignal={openSignal}
      bare={bare}
      error={
        error ??
        (loadFailed ? t("entities.attributes.targetLoadFailed") : undefined)
      }
      data={data}
      value={value || null}
      onChange={(next) => {
        if (!next) {
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
        const entity = entities.find((item) => item.id === next);
        onChange({
          target_entity_id: next,
          target_name: entity?.name ?? (next === value ? cachedName : ""),
          target_table_name:
            entity?.table_name ?? (next === value ? cachedTableName : ""),
        });
      }}
      searchable
      searchValue={search}
      onSearchChange={setSearch}
      filter={({ options }) => options}
      clearable
      nothingFoundMessage={
        loading
          ? "…"
          : loadFailed
            ? t("entities.attributes.targetLoadFailed")
            : t("entities.attributes.targetNothingFound")
      }
      comboboxProps={{ withinPortal: true }}
    />
  );
}
