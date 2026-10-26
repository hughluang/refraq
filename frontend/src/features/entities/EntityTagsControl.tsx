"use client";

import { Button, Group, Stack, Text, TextInput } from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import { useEffect, useState } from "react";

import { SectionHeader } from "@/components/layout/SectionHeader";
import { replaceEntityTags } from "@/features/entities/api";
import type { EntityTag } from "@/features/entities/types";
import { listTags } from "@/features/tags/api";
import { problemMessage } from "@/lib/problem";

type Draft = {
  tag_ids: string[];
  names: string[];
};

type Props = {
  mode: "create" | "show" | "edit";
  entityId?: string;
  tags: EntityTag[];
  tagRevision: number;
  editable: boolean;
  onDraftChange?: (draft: Draft) => void;
  onSaved?: (next: { tags: EntityTag[]; tag_revision: number }) => void;
};

export function EntityTagsControl({
  mode,
  entityId,
  tags,
  tagRevision,
  editable,
  onDraftChange,
  onSaved,
}: Props) {
  const t = useTranslate();
  const { open } = useNotification();
  const [selected, setSelected] = useState<EntityTag[]>(tags);
  const [pending, setPending] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [matches, setMatches] = useState<EntityTag[]>([]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    setSelected(tags);
    setPending([]);
    setQuery("");
  }, [tagRevision, tags]);

  useEffect(() => {
    const needle = query.trim();
    if (!editable || needle === "") {
      setMatches([]);
      return;
    }
    let cancelled = false;
    void listTags({ q: needle, limit: 8 })
      .then((page) => {
        if (!cancelled) {
          setMatches(page.items.map((item) => ({ id: item.id, name: item.name })));
        }
      })
      .catch(() => {
        if (!cancelled) setMatches([]);
      });
    return () => {
      cancelled = true;
    };
  }, [editable, query]);

  function emit(nextSelected: EntityTag[], nextPending: string[]) {
    onDraftChange?.({
      tag_ids: nextSelected.map((tag) => tag.id),
      names: nextPending,
    });
  }

  function commit(raw: string): { selected: EntityTag[]; pending: string[] } {
    const name = raw.trim();
    if (name === "") return { selected, pending };
    const match = matches.find((item) => item.name.toLowerCase() === name.toLowerCase());
    if (match) {
      if (selected.some((tag) => tag.id === match.id)) {
        return { selected, pending };
      }
      const nextSelected = [...selected, match];
      emit(nextSelected, pending);
      return { selected: nextSelected, pending };
    }
    if (pending.some((item) => item.toLowerCase() === name.toLowerCase())) {
      return { selected, pending };
    }
    const nextPending = [...pending, name];
    emit(selected, nextPending);
    return { selected, pending: nextPending };
  }

  function addCommitted(raw: string) {
    const next = commit(raw);
    setSelected(next.selected);
    setPending(next.pending);
    setQuery("");
    setMatches([]);
  }

  function removeSelected(id: string) {
    const nextSelected = selected.filter((tag) => tag.id !== id);
    setSelected(nextSelected);
    emit(nextSelected, pending);
  }

  function removePending(name: string) {
    const nextPending = pending.filter((item) => item !== name);
    setPending(nextPending);
    emit(selected, nextPending);
  }

  async function save() {
    if (!entityId) return;
    const next = commit(query);
    setSelected(next.selected);
    setPending(next.pending);
    setQuery("");
    setSaving(true);
    try {
      const saved = await replaceEntityTags(entityId, {
        base_revision: tagRevision,
        tag_ids: next.selected.map((tag) => tag.id),
        names: next.pending,
      });
      setSelected(saved.tags);
      setPending([]);
      onSaved?.(saved);
      open?.({ type: "success", message: t("entities.tags.saved") });
    } catch (err) {
      open?.({
        type: "error",
        message: problemMessage(t, err, t("entities.tags.failed")),
      });
    } finally {
      setSaving(false);
    }
  }

  const names = [...selected.map((tag) => tag.name), ...pending];

  return (
    <Stack gap="sm">
      <SectionHeader
        order={4}
        title={t("entities.tags.title")}
        description={t("entities.tags.description")}
      />
      {names.length === 0 ? (
        <Text size="sm" c="dimmed">
          {t("entities.tags.empty")}
        </Text>
      ) : (
        <Group gap="xs">
          {selected.map((tag) =>
            editable ? (
              <Button
                key={tag.id}
                type="button"
                size="sm"
                variant="light"
                onClick={() => removeSelected(tag.id)}
              >
                {t("entities.tags.remove", { name: tag.name })}
              </Button>
            ) : (
              <Text key={tag.id} size="sm">
                {tag.name}
              </Text>
            ),
          )}
          {pending.map((name) => (
            <Button
              key={name}
              type="button"
              size="sm"
              variant="light"
              onClick={() => removePending(name)}
            >
              {t("entities.tags.remove", { name })}
            </Button>
          ))}
        </Group>
      )}
      {editable ? (
        <Stack gap="xs">
          <TextInput
            label={t("entities.tags.field")}
            value={query}
            onChange={(event) => setQuery(event.currentTarget.value)}
            onKeyDown={(event) => {
              if (event.key !== "Enter") return;
              event.preventDefault();
              addCommitted(query);
            }}
          />
          {matches.length > 0 ? (
            <Group gap="xs">
              {matches.map((match) => (
                <Button
                  key={match.id}
                  type="button"
                  size="sm"
                  variant="default"
                  onClick={() => addCommitted(match.name)}
                >
                  {match.name}
                </Button>
              ))}
            </Group>
          ) : null}
          {mode === "create" ? null : (
            <Group>
              <Button type="button" size="sm" loading={saving} onClick={() => void save()}>
                {t("entities.tags.save")}
              </Button>
            </Group>
          )}
        </Stack>
      ) : null}
    </Stack>
  );
}
