"use client";

import { Button, Group, MultiSelect, Select, TextInput } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useRef, useState, type ReactNode } from "react";

import {
  isChannelCanvasTarget,
  isEditableShortcutTarget,
} from "@/components/layout/consoleNav";
import type { ListQuery } from "@/hooks/useListQuery";
import { SEARCH_DEBOUNCE_MS } from "@/hooks/useSearchDebounce";

export type ListToolbarField = {
  key: string;
  label: string;
  options: readonly { value: string; label: string }[];
};

export type ListToolbarProps = {
  query: ListQuery;
  searchPlaceholder?: string;
  filters?: readonly ListToolbarField[];
  /** Extra filter control, rendered before Clear. */
  extra?: ReactNode;
};

export function ListToolbar({
  query,
  searchPlaceholder,
  filters = [],
  extra = null,
}: ListToolbarProps) {
  const t = useTranslate();
  const inputRef = useRef<HTMLInputElement>(null);
  const [draft, setDraft] = useState(query.search);
  const setSearchRef = useRef(query.setSearch);
  setSearchRef.current = query.setSearch;
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  function clearTimer() {
    if (timer.current === null) return;
    clearTimeout(timer.current);
    timer.current = null;
  }

  useEffect(() => {
    setDraft(query.search);
    clearTimer();
  }, [query.search]);

  useEffect(() => () => clearTimer(), []);

  useEffect(() => {
    if (!query.searchEnabled) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "/" || event.ctrlKey || event.metaKey || event.altKey) return;
      if (event.isComposing) return;
      if (isEditableShortcutTarget(event.target)) return;
      if (isChannelCanvasTarget(event.target)) return;
      event.preventDefault();
      inputRef.current?.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [query.searchEnabled]);

  function schedule(value: string) {
    clearTimer();
    timer.current = setTimeout(() => {
      timer.current = null;
      setSearchRef.current(value);
    }, SEARCH_DEBOUNCE_MS);
  }

  return (
    <Group gap="sm" wrap="wrap">
      {query.searchEnabled ? (
        <TextInput
          ref={inputRef}
          aria-label={t("common.list.search")}
          placeholder={searchPlaceholder ?? t("common.list.search")}
          value={draft}
          onChange={(event) => {
            const value = event.currentTarget.value;
            setDraft(value);
            schedule(value);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter") {
              event.preventDefault();
              clearTimer();
              setSearchRef.current(draft);
            }
            if (event.key === "Escape") {
              if (draft === "" && query.search === "") return;
              event.preventDefault();
              event.stopPropagation();
              setDraft("");
              clearTimer();
              setSearchRef.current("");
            }
          }}
          w={280}
        />
      ) : null}
      {filters.map((field) => {
        const spec = query.filters.find((item) => item.key === field.key);
        if (!spec) return null;
        const data = field.options.map((option) => ({
          value: option.value,
          label: option.label,
        }));
        if (spec.type === "multi") {
          const value = [...query.multi(field.key)];
          return (
            <MultiSelect
              key={field.key}
              aria-label={field.label}
              placeholder={value.length === 0 ? field.label : undefined}
              data={data}
              value={value}
              onChange={(next) => query.setFilter(field.key, next)}
              searchable={false}
              clearable
              w="max-content"
              miw={280}
              styles={{
                root: { flexShrink: 0 },
                wrapper: { width: "max-content" },
                input: { width: "max-content", minWidth: 280 },
                pillsList: { flexWrap: "nowrap" },
                pill: { flexShrink: 0, maxWidth: "none" },
              }}
            />
          );
        }
        return (
          <Select
            key={field.key}
            aria-label={field.label}
            placeholder={field.label}
            data={data}
            value={query.select(field.key) || null}
            onChange={(next) => query.setFilter(field.key, next ?? "")}
            searchable={false}
            clearable
            miw={220}
          />
        );
      })}
      {extra}
      {query.isFiltered ? (
        <Button type="button" variant="subtle" size="xs" onClick={query.clear}>
          {t("common.filters.clear")}
        </Button>
      ) : null}
    </Group>
  );
}
