"use client";

import { Button, Combobox, Group, Pill, PillsInput, Stack, Text, useCombobox } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { forwardRef, useEffect, useId, useImperativeHandle, useRef, useState } from "react";

import { SectionHeader } from "@/components/layout/SectionHeader";
import { tagAssignmentKey } from "@/features/tags/assignmentKey";
import { listTags } from "@/features/tags/api";
import { commitTagDraft } from "@/features/tags/commitTagDraft";
import { TagNameBadge } from "@/features/tags/TagNameBadge";

const SEARCH_DEBOUNCE_MS = 250;
const TAG_LIMIT = 10;
const CREATE_OPTION = "__create__";

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

function folded(value: string) {
  return value.trim().toLowerCase();
}

function isDuplicateName(
  name: string,
  selected: readonly RecordTag[],
  pending: readonly string[],
) {
  const key = folded(name);
  if (key === "") return false;
  return (
    pending.some((item) => folded(item) === key) ||
    selected.some((tag) => folded(tag.name) === key)
  );
}

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

function sameDraft(draft: RecordTagDraft, loaded: readonly RecordTag[]) {
  if (draft.names.length > 0) return false;
  if (draft.tag_ids.length !== loaded.length) return false;
  const ids = new Set(loaded.map((tag) => tag.id));
  return draft.tag_ids.every((id) => ids.has(id));
}

export const RecordTagEditor = forwardRef<RecordTagEditorHandle, RecordTagEditorProps>(
  function RecordTagEditor(
    {
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
    const titleId = useId();
    const fieldRef = useRef<HTMLInputElement>(null);
    const [selected, setSelected] = useState<RecordTag[]>([...tags]);
    const [pending, setPending] = useState<string[]>([]);
    const [query, setQuery] = useState("");
    const [matches, setMatches] = useState<RecordTag[]>([]);
    const [searchFailed, setSearchFailed] = useState(false);
    const [searching, setSearching] = useState(false);
    const [saving, setSaving] = useState(false);
    const [retryNonce, setRetryNonce] = useState(0);
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
      // A reload replaces the saved chips. Text still in the field stays there.
      setSelected([...tags]);
      setPending([]);
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
      setSearching(true);
      setSearchFailed(false);
      setMatches([]);
      resetSelection.current();
      const timer = window.setTimeout(() => {
        void listTags({ q: needle, limit: 8, signal: controller.signal }).then(
          (page) => {
            if (controller.signal.aborted) return;
            setMatches(page.items.map((item) => ({ id: item.id, name: item.name })));
            setSearching(false);
            resetSelection.current();
          },
          () => {
            if (controller.signal.aborted) return;
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
    }, [editable, query, retryNonce]);

    const flushRef = useRef<() => RecordTagDraft>(() => ({ tag_ids: [], names: [] }));
    flushRef.current = () => {
      const name = query.trim();
      const draft = {
        tag_ids: selected.map((tag) => tag.id),
        names: [...pending],
      };
      if (name === "") {
        combobox.resetSelectedOption();
        combobox.closeDropdown();
        return draft;
      }
      if (
        searchFailed ||
        isDuplicateName(name, selected, pending) ||
        selected.length + pending.length >= TAG_LIMIT
      ) {
        combobox.openDropdown();
        return draft;
      }
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
      if (!onSave || sameDraft(draft, tags)) return;
      setSaving(true);
      try {
        await onSave(draft);
      } finally {
        setSaving(false);
      }
    }

    function focusField() {
      fieldRef.current?.focus();
    }

    function addKnown(tag: RecordTag) {
      setSelected([...selected, tag]);
      setQuery("");
      setMatches([]);
      combobox.resetSelectedOption();
      combobox.closeDropdown();
    }

    const nameCount = selected.length + pending.length;
    const needle = query.trim();
    const duplicate = isDuplicateName(needle, selected, pending);
    const exactHit = matches.some((item) => folded(item.name) === folded(needle));
    const capped = nameCount >= TAG_LIMIT;
    const blocked = capped && needle !== "" && !duplicate;
    const showCreate =
      !searching && !searchFailed && needle !== "" && !duplicate && !exactHit && !capped;
    const dirty = needle !== "" || !sameLoadedSet(selected, pending, tags);
    const showEmpty = !editable && selected.length === 0;
    const options = matches.filter((match) => {
      if (selected.some((tag) => tag.id === match.id)) return false;
      return !pending.some((item) => folded(item) === folded(match.name));
    });

    return (
      <Stack gap="sm">
        <SectionHeader
          order={4}
          title={title}
          titleId={titleId}
          description={description}
          actions={
            editable && saveLabel ? (
              <>
                {dirty ? (
                  <Text size="sm" c="dimmed">
                    {t("tags.editor.unsaved")}
                  </Text>
                ) : null}
                <Button
                  type="button"
                  size="sm"
                  variant="light"
                  loading={saving}
                  disabled={!dirty || saving}
                  onClick={() => void save()}
                >
                  {saveLabel}
                </Button>
              </>
            ) : null
          }
        />
        {showEmpty ? (
          <Text size="sm" c="dimmed">
            {emptyLabel}
          </Text>
        ) : null}
        {editable ? (
          <Combobox
            store={combobox}
            onOptionSubmit={(value) => {
              if (value === CREATE_OPTION) {
                flushRef.current();
                return;
              }
              const tag = matchesRef.current.find((item) => item.id === value);
              if (tag) addKnown(tag);
            }}
          >
            <Combobox.DropdownTarget>
              <PillsInput
                description={t("tags.editor.limitHint")}
                error={
                  blocked
                    ? t("tags.editor.limitBlocked")
                    : duplicate
                      ? t("tags.editor.duplicate")
                      : undefined
                }
                onClick={() => {
                  if (query.trim() !== "") combobox.openDropdown();
                }}
              >
                <Pill.Group>
                  {selected.map((tag) => (
                    <Pill
                      key={tag.id}
                      maw="100%"
                      withRemoveButton
                      onRemove={() => {
                        setSelected((current) => current.filter((item) => item.id !== tag.id));
                        focusField();
                      }}
                      removeButtonProps={{
                        "aria-label": removeLabel(tag.name),
                        "aria-hidden": false,
                      }}
                    >
                      <span style={{ overflowWrap: "anywhere", minWidth: 0 }}>{tag.name}</span>
                    </Pill>
                  ))}
                  {pending.map((name) => (
                    <Pill
                      key={name}
                      maw="100%"
                      mod={{ pending: true }}
                      withRemoveButton
                      style={{
                        border: "1px dashed var(--mantine-color-gray-5)",
                        background: "transparent",
                      }}
                      onRemove={() => {
                        setPending((current) => current.filter((item) => item !== name));
                        focusField();
                      }}
                      removeButtonProps={{
                        "aria-label": removeLabel(name),
                        "aria-hidden": false,
                      }}
                    >
                      <span style={{ overflowWrap: "anywhere", minWidth: 0 }}>{name}</span>
                    </Pill>
                  ))}
                  <Combobox.EventsTarget withExpandedAttribute>
                    <PillsInput.Field
                      ref={fieldRef}
                      aria-labelledby={titleId}
                      value={query}
                      placeholder={nameCount === 0 ? t("tags.editor.placeholder") : undefined}
                      onFocus={() => {
                        if (query.trim() !== "") combobox.openDropdown();
                      }}
                      onBlur={() => {
                        combobox.closeDropdown();
                      }}
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
                          if (combobox.dropdownOpened) {
                            combobox.resetSelectedOption();
                            return;
                          }
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
                        }
                        if (event.key !== "Enter") return;
                        if (combobox.dropdownOpened && combobox.getSelectedOptionIndex() !== -1) {
                          return;
                        }
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
                {searchFailed ? (
                  <Combobox.Empty>
                    <Stack gap={6} align="flex-start">
                      <Text size="sm">{t("tags.editor.searchFailed")}</Text>
                      <Button
                        type="button"
                        size="xs"
                        variant="light"
                        onMouseDown={(event) => event.preventDefault()}
                        onClick={() => setRetryNonce((value) => value + 1)}
                      >
                        {t("common.retry")}
                      </Button>
                    </Stack>
                  </Combobox.Empty>
                ) : null}
                {!searching && !searchFailed && duplicate ? (
                  <Combobox.Empty>{t("tags.editor.duplicate")}</Combobox.Empty>
                ) : null}
                {!searching && !searchFailed && blocked ? (
                  <Combobox.Empty>{t("tags.editor.limitBlocked")}</Combobox.Empty>
                ) : null}
                {!searching && !searchFailed && !capped
                  ? options.map((match) => (
                      <Combobox.Option key={match.id} value={match.id}>
                        {match.name}
                      </Combobox.Option>
                    ))
                  : null}
                {showCreate ? (
                  <Combobox.Option value={CREATE_OPTION}>
                    {t("tags.editor.create", { name: needle })}
                  </Combobox.Option>
                ) : null}
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
      </Stack>
    );
  },
);
