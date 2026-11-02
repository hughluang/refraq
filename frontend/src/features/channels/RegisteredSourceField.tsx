"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { useTranslate } from "@refinedev/core";

import { SelectField } from "@/components/form/SelectField";
import type { FieldNote } from "@/components/form/fieldNotes";
import type { SourceDisplay } from "@/features/channels/types";
import { listSources } from "@/features/sources/api/sources";

export type SourceOption = { value: string; label: string };

const SourceDisplaysContext = createContext<readonly SourceDisplay[]>([]);

export function SourceDisplaysProvider({
  displays,
  children,
}: {
  displays: readonly SourceDisplay[];
  children: ReactNode;
}) {
  return (
    <SourceDisplaysContext.Provider value={displays}>{children}</SourceDisplaysContext.Provider>
  );
}

export function useSourceDisplay(sourceId: string | null): SourceDisplay | null {
  const displays = useContext(SourceDisplaysContext);
  if (!sourceId) return null;
  return displays.find((item) => item.source_id === sourceId) ?? null;
}

export function sourceSelectData(
  options: readonly SourceOption[],
  selected: string | null,
  display: SourceDisplay | null,
  marker: string,
  loaded: boolean,
): SourceOption[] {
  if (!selected) return [...options];
  if (display?.inaccessible) {
    return [
      ...options.filter((option) => option.value !== selected),
      { value: selected, label: marker },
    ];
  }
  if (options.some((option) => option.value === selected)) return [...options];
  if (display?.name) return [...options, { value: selected, label: display.name }];
  if (!loaded) return [...options, { value: selected, label: selected }];
  return [...options, { value: selected, label: marker }];
}

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
  const { options, loadFailed, loaded } = useSourceOptions();

  const selected = typeof value === "string" && value !== "" ? value : null;
  const display = useSourceDisplay(selected);
  const data = sourceSelectData(
    options,
    selected,
    display,
    t("channels.config.source.inaccessible"),
    loaded,
  );

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

export function useSourceOptions(): {
  options: SourceOption[];
  loadFailed: boolean;
  loaded: boolean;
} {
  const [options, setOptions] = useState<SourceOption[]>([]);
  const [loadFailed, setLoadFailed] = useState(false);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    listSources({ limit: 100 })
      .then((page) => {
        if (cancelled) return;
        setLoadFailed(false);
        setLoaded(true);
        setOptions(page.items.map((source) => ({ value: source.id, label: source.name })));
      })
      .catch(() => {
        if (cancelled) return;
        setLoadFailed(true);
        setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return { options, loadFailed, loaded };
}
