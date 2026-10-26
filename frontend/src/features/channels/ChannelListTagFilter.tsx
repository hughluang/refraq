"use client";

import { MultiSelect } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useMemo, useState } from "react";

import type { ChannelTag } from "@/features/channels/types";
import { listTags } from "@/features/tags/api";

type Props = {
  value: readonly string[];
  onChange: (ids: string[]) => void;
  known: ReadonlyMap<string, string>;
};

export function ChannelListTagFilter({ value, onChange, known }: Props) {
  const t = useTranslate();
  const [search, setSearch] = useState("");
  const [matches, setMatches] = useState<ChannelTag[]>([]);
  const [labels, setLabels] = useState<ReadonlyMap<string, string>>(() => new Map());

  useEffect(() => {
    setLabels((current) => {
      let changed = false;
      const next = new Map(current);
      for (const [id, name] of known) {
        if (next.get(id) === name) continue;
        next.set(id, name);
        changed = true;
      }
      return changed ? next : current;
    });
  }, [known]);

  useEffect(() => {
    const needle = search.trim();
    if (needle === "") {
      setMatches([]);
      return;
    }
    let cancelled = false;
    void listTags({ q: needle, limit: 8 })
      .then((page) => {
        if (cancelled) return;
        const found = page.items.map((item) => ({ id: item.id, name: item.name }));
        setMatches(found);
        setLabels((current) => {
          let changed = false;
          const next = new Map(current);
          for (const tag of found) {
            if (next.get(tag.id) === tag.name) continue;
            next.set(tag.id, tag.name);
            changed = true;
          }
          return changed ? next : current;
        });
      })
      .catch(() => {
        if (!cancelled) setMatches([]);
      });
    return () => {
      cancelled = true;
    };
  }, [search]);

  const data = useMemo(() => {
    const byId = new Map<string, string>();
    for (const id of value) byId.set(id, labels.get(id) ?? known.get(id) ?? id);
    for (const tag of matches) byId.set(tag.id, tag.name);
    return [...byId].map(([id, label]) => ({ value: id, label }));
  }, [known, labels, matches, value]);

  return (
    <MultiSelect
      aria-label={t("channels.list.tagFilter")}
      placeholder={value.length === 0 ? t("channels.list.tagFilter") : undefined}
      data={data}
      value={[...value]}
      onChange={onChange}
      searchValue={search}
      onSearchChange={setSearch}
      searchable
      clearable
      hidePickedOptions
      filter={({ options }) => options}
      nothingFoundMessage={
        search.trim() === "" ? undefined : t("channels.list.tagNone")
      }
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
