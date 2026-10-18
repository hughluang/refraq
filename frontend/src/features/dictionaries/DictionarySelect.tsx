"use client";

import { Anchor, Badge, Button, Group, Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useState } from "react";

import { RecordPicker } from "@/components/form/RecordPicker";
import {
  cachedDictionary,
  dictionaryRecordAdapter,
  rememberDictionary,
} from "@/components/form/recordPickerAdapters";
import { getDictionary } from "@/features/dictionaries/api";
import { CreateDictionaryModal } from "@/features/dictionaries/CreateDictionaryModal";
import { DictionaryStatusBadge } from "@/features/dictionaries/DictionaryStatusBadge";
import type { DictionaryEntry } from "@/features/dictionaries/types";

export type DictionarySelection = {
  dictionary_id: string;
  dictionary_name: string;
  dictionary_display_name: string;
  dictionary_deprecated: boolean;
  behind: boolean;
};

type Props = {
  editable: boolean;
  value: string;
  name: string;
  displayName: string;
  deprecated: boolean;
  behind: boolean;
  error?: string;
  onChange: (next: DictionarySelection) => void;
};

export function DictionarySelect({
  editable,
  value,
  name,
  displayName,
  deprecated,
  behind,
  error,
  onChange,
}: Props) {
  const t = useTranslate();
  const [preview, setPreview] = useState<DictionaryEntry[] | null>(null);
  const [previewFailed, setPreviewFailed] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);
  const loadFailedMessage = t("common.error.loadFailed");
  const selectedLabel = displayName.trim() || name.trim() || value;

  useEffect(() => {
    if (!value) {
      setPreview(null);
      setPreviewFailed(false);
      return;
    }
    let cancelled = false;
    setPreviewFailed(false);
    void getDictionary(value).then(
      (response) => {
        if (cancelled) return;
        setPreview(response.dictionary.entries ?? []);
        setPreviewFailed(false);
      },
      () => {
        if (cancelled) return;
        setPreview(null);
        setPreviewFailed(true);
      },
    );
    return () => {
      cancelled = true;
    };
  }, [value]);

  const active = (preview ?? []).filter((entry) => entry.active);
  const inactive = (preview ?? []).filter((entry) => !entry.active);

  return (
    <Stack gap="xs">
      <RecordPicker
        editable={editable}
        required
        label={t("entities.fields.dictionary")}
        description={t("entities.fields.dictionaryHint")}
        adapter={dictionaryRecordAdapter()}
        value={value || null}
        error={error}
        known={
          value
            ? [{ id: value, name: selectedLabel, key: name.trim() || value }]
            : undefined
        }
        onChange={(next) => {
          if (!next) {
            onChange({
              dictionary_id: "",
              dictionary_name: "",
              dictionary_display_name: "",
              dictionary_deprecated: false,
              behind: false,
            });
            return;
          }
          const picked = cachedDictionary(next);
          onChange({
            dictionary_id: next,
            dictionary_name: picked?.name ?? "",
            dictionary_display_name: picked?.display_name ?? "",
            dictionary_deprecated: picked?.deprecated_at != null,
            behind: false,
          });
        }}
      />
      <Group gap="sm">
        {editable ? (
          <Button
            type="button"
            variant="default"
            size="xs"
            onClick={() => setCreateOpen(true)}
          >
            {t("entities.fields.createDictionary")}
          </Button>
        ) : null}
        {value ? (
          <Anchor href={`/console/dictionaries/${value}`} target="_blank" size="sm">
            {t("entities.fields.openDictionary")}
          </Anchor>
        ) : null}
        {deprecated ? <DictionaryStatusBadge deprecated /> : null}
        {behind ? (
          <Badge color="orange" variant="light">
            {t("entities.attributes.behind")}
          </Badge>
        ) : null}
      </Group>
      {value ? (
        <Stack gap={4}>
          <Text size="sm" fw={500}>
            {t("entities.fields.dictionaryPreview")}
          </Text>
          {previewFailed ? (
            <Text size="sm" c="red">
              {loadFailedMessage}
            </Text>
          ) : active.length === 0 ? (
            <Text size="sm" c="dimmed">
              {t("entities.fields.dictionaryPreviewEmpty")}
            </Text>
          ) : (
            <Text size="sm">
              {active
                .map((entry) =>
                  entry.label ? `${entry.code} (${entry.label})` : entry.code,
                )
                .join(", ")}
            </Text>
          )}
          {!previewFailed && inactive.length > 0 ? (
            <Text size="xs" c="dimmed">
              {t("entities.fields.dictionaryInactive", {
                codes: inactive.map((entry) => entry.code).join(", "),
              })}
            </Text>
          ) : null}
        </Stack>
      ) : null}
      <CreateDictionaryModal
        opened={createOpen}
        onClose={() => setCreateOpen(false)}
        onCreated={(created) => {
          rememberDictionary(created);
          onChange({
            dictionary_id: created.id,
            dictionary_name: created.name,
            dictionary_display_name: created.display_name,
            dictionary_deprecated: false,
            behind: false,
          });
        }}
      />
    </Stack>
  );
}
