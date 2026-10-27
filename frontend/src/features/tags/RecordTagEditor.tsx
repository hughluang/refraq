"use client";

import {
  ActionIcon,
  Badge,
  Button,
  Combobox,
  Group,
  Pill,
  PillsInput,
  Stack,
  Text,
  useCombobox,
} from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";

import { CloseIcon } from "@/components/icons";
import { SectionHeader } from "@/components/layout/SectionHeader";
import { tagAssignmentKey } from "@/features/tags/assignmentKey";
import { listTags } from "@/features/tags/api";
import { commitTagDraft } from "@/features/tags/commitTagDraft";
import { TagNameBadge } from "@/features/tags/TagNameBadge";

const SEARCH_DEBOUNCE_MS = 250;
const TAG_LIMIT = 10;

export type RecordTag = {
  id: string;
  name: string;
};

export type RecordTagDraft = {
  tag_ids: string[];
  names: string[];
};

export type RecordTagEditorHandle = {
  flush: () => RecordTagDraft;
};

export type RecordTagEditorProps = {
  fieldLabel: string;
  title: string;
  description: string;
  emptyLabel: string;
  removeLabel: (name: string) => string;
  saveLabel?: string;
  editable?: boolean;
  tags: readonly RecordTag[];
  tagRevision: number;
  onDraftChange?: (draft: RecordTagDraft) => void;
  onSave?: (draft: RecordTagDraft) => Promise<unknown>;
};

function sameLoadedSet(
  selected: readonly RecordTag[],
  pending: readonly string[],
  loaded: readonly RecordTag[],
) {
  if (pending.length > 0) return false;
  if (selected.length !== loaded.length) return false;
  const ids = new Set(loaded.map((tag) => tag.id));
  return selected.every((tag) => ids.has(tag.id));
}

export const RecordTagEditor = forwardRef<RecordTagEditorHandle, RecordTagEditorProps>(
  function RecordTagEditor(
    {
      fieldLabel,
      title,
      description,
      emptyLabel,
      removeLabel,
      saveLabel,
      editable = true,
      tags,
      tagRevision,
      onDraftChange,
      onSave,
    },
    ref,
  ) {
  const t = useTranslate();
  const [selected, setSelected] = useState<RecordTag[]>([...tags]);
  const [pending, setPending] = useState<string[]>([]);
  const [query, setQuery] = useState("");
  const [matches, setMatches] = useState<RecordTag[]>([]);
  const [searchFailed, setSearchFailed] = useState(false);
  const [searching, setSearching] = useState(false);
  const [saving, setSaving] = useState(false);
  const matchesRef = useRef(matches);
  matchesRef.current = matches;

  const combobox = useCombobox();
  const resetSelection = useRef(combobox.resetSelectedOption);
  resetSelection.current = combobox.resetSelectedOption;

  const assignmentKey = tagAssignmentKey(tagRevision, tags);
  const seenAssignment = useRef(assignmentKey);
  useEffect(() => {
    if (seenAssignment.current === assignmentKey) return;
    seenAssignment.current = assignmentKey;
    setSelected([...tags]);
    setPending([]);
    setQuery("");
    setMatches([]);
  }, [assignmentKey, tags]);

  useEffect(() => {
    const needle = query.trim();
    if (!editable || needle === "") {
      setMatches((current) => (current.length === 0 ? current : []));
      setSearchFailed((current) => (current ? false : current));
      setSearching((current) => (current ? false : current));
      resetSelection.current();
      return;
    }
    const controller = new AbortController();
    const timer = window.setTimeout(() => {
      setSearching(true);
      void listTags({ q: needle, limit: 8, signal: controller.signal }).then(
        (page) => {
          if (controller.signal.aborted) return;
          setMatches(page.items.map((item) => ({ id: item.id, name: item.name })));
          setSearchFailed(false);
          setSearching(false);
          resetSelection.current();
        },
        () => {
          if (controller.signal.aborted) return;
          setMatches((current) => (current.length === 0 ? current : []));
          setSearchFailed(true);
          setSearching(false);
          resetSelection.current();
        },
      );
    }, SEARCH_DEBOUNCE_MS);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [editable, query]);

  const flushRef = useRef<() => RecordTagDraft>(() => ({ tag_ids: [], names: [] }));
  flushRef.current = () => {
    const next = commitTagDraft({
      raw: query,
      selected,
      pending,
      matches: matchesRef.current,
    });
    setSelected([...next.selected]);
    setPending(next.pending);
    setQuery("");
    setMatches([]);
    combobox.resetSelectedOption();
    combobox.closeDropdown();
    return next.draft;
  };

  useImperativeHandle(ref, () => ({
    flush: () => flushRef.current(),
  }));

  useEffect(() => {
    onDraftChange?.({
      tag_ids: selected.map((tag) => tag.id),
      names: pending,
    });
  }, [onDraftChange, pending, selected]);

  async function save() {
    const draft = flushRef.current();
    if (!onSave) return;
    setSaving(true);
    try {
      await onSave(draft);
    } finally {
      setSaving(false);
    }
  }

  function addKnown(tag: RecordTag) {
    setSelected([...selected, tag]);
    setQuery("");
    setMatches([]);
    combobox.resetSelectedOption();
    combobox.closeDropdown();
  }

  const nameCount = selected.length + pending.length;

  const showEmpty = selected.length === 0 && pending.length === 0 && query.trim() === "";
  const options = matches.filter((match) => {
    if (selected.some((tag) => tag.id === match.id)) return false;
    const name = match.name.trim().toLowerCase();
    return !pending.some((item) => item.toLowerCase() === name);
  });

  return (
    <Stack gap="sm">
      <SectionHeader
        order={4}
        title={title}
        description={description}
        actions={
          editable && saveLabel ? (
            <Button
              type="button"
              size="sm"
              variant="light"
              loading={saving}
              disabled={query.trim() === "" && sameLoadedSet(selected, pending, tags)}
              onClick={() => void save()}
            >
              {saveLabel}
            </Button>
          ) : null
        }
      />
      {showEmpty ? (
        <Text size="sm" c="dimmed">
          {emptyLabel}
        </Text>
      ) : null}
      {editable && nameCount >= TAG_LIMIT ? (
        <Text size="sm">{t("tags.editor.limit")}</Text>
      ) : null}
      {editable ? (
      <Combobox
        store={combobox}
        onOptionSubmit={(value) => {
          const tag = matchesRef.current.find((item) => item.id === value);
          if (tag) addKnown(tag);
        }}
      >
        <Combobox.DropdownTarget>
          <PillsInput
            label={fieldLabel}
            onClick={() => {
              if (query.trim() !== "") combobox.openDropdown();
            }}
          >
            <Pill.Group>
              {selected.map((tag) => (
                <Group key={tag.id} gap={4} wrap="nowrap">
                  <TagNameBadge name={tag.name} />
                  <ActionIcon
                    type="button"
                    variant="subtle"
                    color="gray"
                    size="sm"
                    aria-label={removeLabel(tag.name)}
                    onClick={() =>
                      setSelected((current) => current.filter((item) => item.id !== tag.id))
                    }
                    onMouseDown={(event) => event.stopPropagation()}
                  >
                    <CloseIcon size={12} />
                  </ActionIcon>
                </Group>
              ))}
              {pending.map((name) => (
                <Group key={name} gap={4} wrap="nowrap">
                  <Badge size="sm" variant="outline" color="gray" tt="none">
                    {name}
                    <Text span size="xs" c="dimmed" ml={4}>
                      {t("tags.editor.new")}
                    </Text>
                  </Badge>
                  <ActionIcon
                    type="button"
                    variant="subtle"
                    color="gray"
                    size="sm"
                    aria-label={removeLabel(name)}
                    onClick={() =>
                      setPending((current) => current.filter((item) => item !== name))
                    }
                    onMouseDown={(event) => event.stopPropagation()}
                  >
                    <CloseIcon size={12} />
                  </ActionIcon>
                </Group>
              ))}
              <Combobox.EventsTarget>
                <PillsInput.Field
                  value={query}
                  onChange={(event) => {
                    const next = event.currentTarget.value;
                    setQuery(next);
                    if (next.trim() === "") {
                      combobox.resetSelectedOption();
                      combobox.closeDropdown();
                    } else {
                      combobox.openDropdown();
                    }
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Escape") {
                      setQuery("");
                      combobox.resetSelectedOption();
                      return;
                    }
                    if (event.key === "Backspace" && query === "") {
                      event.preventDefault();
                      if (pending.length > 0) {
                        setPending(pending.slice(0, -1));
                        return;
                      }
                      if (selected.length > 0) setSelected(selected.slice(0, -1));
                      return;
                    }
                    if (event.key !== "Enter") return;
                    if (combobox.dropdownOpened && combobox.getSelectedOptionIndex() !== -1) return;
                    event.preventDefault();
                    flushRef.current();
                  }}
                />
              </Combobox.EventsTarget>
            </Pill.Group>
          </PillsInput>
        </Combobox.DropdownTarget>
        <Combobox.Dropdown>
          <Combobox.Options>
            {searching ? <Combobox.Empty>{t("tags.editor.searching")}</Combobox.Empty> : null}
            {options.map((match) => (
              <Combobox.Option key={match.id} value={match.id}>
                {match.name}
              </Combobox.Option>
            ))}
          </Combobox.Options>
        </Combobox.Dropdown>
      </Combobox>
      ) : (
        <Group gap="xs">
          {selected.map((tag) => (
            <TagNameBadge key={tag.id} name={tag.name} />
          ))}
        </Group>
      )}
      {editable && searchFailed ? (
        <Text size="sm">{t("tags.editor.searchFailed")}</Text>
      ) : null}
    </Stack>
  );
},
);
