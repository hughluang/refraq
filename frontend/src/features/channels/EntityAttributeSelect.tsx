"use client";

import { type SelectProps } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

import { SelectField } from "@/components/form/SelectField";
import type { FieldNote } from "@/components/form/fieldNotes";
import type { EntityAttribute } from "@/features/entities/types";

const EMPTY = "__business_key__";

type Props = {
  entityId: string;
  label?: string;
  "aria-label"?: string;
  value: string | null;
  editable: boolean;
  allowEmpty?: boolean;
  exclude?: readonly string[];
  attributes: readonly EntityAttribute[];
  failed?: boolean;
  notes?: readonly FieldNote[];
  openSignal?: string | null;
  bare?: boolean;
  size?: SelectProps["size"];
  onChange: (next: string | null) => void;
};

export function EntityAttributeSelect({
  entityId,
  label,
  "aria-label": ariaLabel,
  value,
  editable,
  allowEmpty = false,
  exclude = [],
  attributes,
  failed = false,
  notes,
  openSignal,
  bare = false,
  size,
  onChange,
}: Props) {
  const t = useTranslate();
  const hidden = new Set(exclude);
  const current = typeof value === "string" ? value : "";
  const options = [
    ...(allowEmpty
      ? [{ value: EMPTY, label: t("channels.config.businessKey") }]
      : []),
    ...attributes
      .filter((attribute) => attribute.name === current || !hidden.has(attribute.name))
      .map((attribute) => ({
        value: attribute.name,
        label: attribute.name,
      })),
  ];
  const selected =
    allowEmpty && (value == null || value === "") ? EMPTY : (value ?? null);

  return (
    <SelectField
      editable={editable}
      label={label}
      aria-label={ariaLabel}
      data={options}
      value={selected}
      size={size}
      w="100%"
      notes={notes}
      openSignal={openSignal}
      bare={bare}
      error={failed ? t("channels.config.attributeLoadFailed") : undefined}
      nothingFoundMessage={
        entityId ? t("channels.config.noAttributes") : t("channels.config.pickEntity")
      }
      onChange={(next) => {
        if (!next || next === EMPTY) onChange(allowEmpty ? null : "");
        else onChange(next);
      }}
      searchable
      comboboxProps={{ withinPortal: true }}
    />
  );
}
