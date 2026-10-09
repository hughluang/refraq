"use client";

import { useTranslate } from "@refinedev/core";
import { useEffect, useState } from "react";

import { SelectField } from "@/components/form/SelectField";
import { getVersion, listVersions } from "@/features/entities/api";
import type { EntityAttribute } from "@/features/entities/types";

const EMPTY = "__business_key__";

type Props = {
  entityId: string;
  label: string;
  value: string | null;
  editable: boolean;
  allowEmpty?: boolean;
  onChange: (next: string | null) => void;
};

export function EntityAttributeSelect({
  entityId,
  label,
  value,
  editable,
  allowEmpty = false,
  onChange,
}: Props) {
  const t = useTranslate();
  const [attributes, setAttributes] = useState<EntityAttribute[]>([]);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!entityId) {
      setAttributes([]);
      setFailed(false);
      return;
    }
    let cancelled = false;
    setFailed(false);
    void listVersions(entityId, { limit: 50 })
      .then(async (page) => {
        const published = page.items
          .filter((item) => item.publish_status === "published")
          .sort((left, right) => right.version - left.version);
        const head = published[0];
        if (!head) {
          if (!cancelled) setAttributes([]);
          return;
        }
        const version = head.attributes
          ? head
          : (await getVersion(entityId, head.id)).version;
        if (!cancelled) setAttributes(version.attributes ?? []);
      })
      .catch(() => {
        if (!cancelled) {
          setAttributes([]);
          setFailed(true);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [entityId]);

  const options = [
    ...(allowEmpty
      ? [{ value: EMPTY, label: t("channels.config.businessKey") }]
      : []),
    ...attributes.map((attribute) => ({
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
      data={options}
      value={selected}
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
