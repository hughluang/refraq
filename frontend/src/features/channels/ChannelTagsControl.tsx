"use client";

import { Button, Group, Stack, Text, TextInput } from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";

import { SectionHeader } from "@/components/layout/SectionHeader";
import { replaceChannelTags } from "@/features/channels/api";
import type { ChannelTag } from "@/features/channels/types";
import { tagAssignmentKey } from "@/features/tags/assignmentKey";
import { commitTagDraft } from "@/features/tags/commitTagDraft";
import { listTags } from "@/features/tags/api";
import { problemMessage } from "@/lib/problem";

type Draft = {
  tag_ids: string[];
  names: string[];
};

export type ChannelTagsControlHandle = {
  flush: () => Draft;
};

type Props = {
  mode: "create" | "show" | "edit";
  channelId?: string;
  tags: ChannelTag[];
  tagRevision: number;
  editable: boolean;
  onDraftChange?: (draft: Draft) => void;
  onSaved?: (next: { tags: ChannelTag[]; tag_revision: number }) => void;
};

export const ChannelTagsControl = forwardRef<ChannelTagsControlHandle, Props>(
  function ChannelTagsControl(
    { mode, channelId, tags, tagRevision, editable, onDraftChange, onSaved },
    ref,
  ) {
  const t = useTranslate();
  const { open } = useNotification();
  const [selected, setSelected] = useState<ChannelTag[]>(tags);
  const [pending, setPending] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [matches, setMatches] = useState<ChannelTag[]>([]);
  const [saving, setSaving] = useState(false);

  // A new array with the same assignment must not drop unsaved names.
  const assignmentKey = tagAssignmentKey(tagRevision, tags);
  const seenAssignment = useRef(assignmentKey);
  useEffect(() => {
    if (seenAssignment.current === assignmentKey) return;
    seenAssignment.current = assignmentKey;
    setSelected(tags);
    setPending([]);
    setQuery("");
  }, [assignmentKey, tags]);

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

  function emit(nextSelected: ChannelTag[], nextPending: string[]) {
    onDraftChange?.({
      tag_ids: nextSelected.map((tag) => tag.id),
      names: nextPending,
    });
  }

  function commit(raw: string) {
    const next = commitTagDraft({ raw, selected, pending, matches });
    if (next.selected !== selected || next.pending !== pending) {
      emit(next.selected, next.pending);
    }
    return next;
  }

  function addCommitted(raw: string) {
    const next = commit(raw);
    setSelected(next.selected);
    setPending(next.pending);
    setQuery("");
    setMatches([]);
  }

  const flushRef = useRef<() => Draft>(() => ({ tag_ids: [], names: [] }));
  flushRef.current = () => {
    const next = commit(query);
    setSelected(next.selected);
    setPending(next.pending);
    setQuery("");
    setMatches([]);
    return next.draft;
  };

  useImperativeHandle(ref, () => ({
    flush: () => flushRef.current(),
  }));

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
    if (!channelId) return;
    const draft = flushRef.current();
    setSaving(true);
    try {
      const saved = await replaceChannelTags(channelId, {
        base_revision: tagRevision,
        tag_ids: draft.tag_ids,
        names: draft.names,
      });
      setSelected(saved.tags);
      setPending([]);
      onSaved?.(saved);
      open?.({ type: "success", message: t("channels.tags.saved") });
    } catch (err) {
      open?.({
        type: "error",
        message: problemMessage(t, err, t("channels.tags.failed")),
      });
    } finally {
      setSaving(false);
    }
  }

  const names = [...selected.map((tag) => tag.name), ...pending];
  const written = commitTagDraft({
    raw: editable ? query : "",
    selected,
    pending,
    matches,
  });
  const writeEmpty = written.draft.tag_ids.length === 0 && written.draft.names.length === 0;

  return (
    <Stack gap="sm">
      <SectionHeader
        order={4}
        title={t("channels.tags.title")}
        description={t(
          mode === "create" ? "channels.tags.createDescription" : "channels.tags.description",
        )}
      />
      {writeEmpty ? (
        <Text size="sm" c="dimmed">
          {t("channels.tags.empty")}
        </Text>
      ) : names.length === 0 ? null : (
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
                {t("channels.tags.remove", { name: tag.name })}
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
              {t("channels.tags.remove", { name })}
            </Button>
          ))}
        </Group>
      )}
      {editable ? (
        <Stack gap="xs">
          <TextInput
            label={t("channels.tags.field")}
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
                {t("channels.tags.save")}
              </Button>
            </Group>
          )}
        </Stack>
      ) : null}
    </Stack>
  );
},
);
