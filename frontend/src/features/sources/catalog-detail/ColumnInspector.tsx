"use client";

import {
  ActionIcon,
  Badge,
  Box,
  Button,
  Divider,
  Drawer,
  Group,
  Paper,
  ScrollArea,
  Stack,
  Text,
  Textarea,
  Tooltip,
} from "@mantine/core";
import { useMediaQuery } from "@mantine/hooks";
import { useNotification, useTranslate } from "@refinedev/core";
import { useEffect, useState } from "react";

import { TextField } from "@/components/form/TextField";
import { TextareaField } from "@/components/form/TextareaField";
import {
  ChevronDownIcon,
  ChevronUpIcon,
  CloseIcon,
  CopyIcon,
  PlusIcon,
  UndoIcon,
} from "@/components/icons";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import {
  type ColumnDraft,
  parseBulkEnumText,
} from "@/features/sources/catalog-detail/columnDrafts";
import { semanticSourceLabel } from "@/features/sources/catalogLabel";
import type {
  CatalogColumn,
  CatalogForeignKey,
} from "@/features/sources/types";
import { copyText } from "@/lib/copy-text";

const QUICK_SEMANTIC_TYPES = [
  "identifier",
  "currency",
  "timestamp",
  "status",
  "email",
  "phone",
  "quantity",
  "percentage",
] as const;

type ColumnInspectorProps = {
  column: CatalogColumn | null;
  draft: ColumnDraft | null;
  writable: boolean;
  isDirty: boolean;
  savingSingle: boolean;
  foreignKeys: readonly CatalogForeignKey[];
  hasPrev: boolean;
  hasNext: boolean;
  onPrev: () => void;
  onNext: () => void;
  onClose: () => void;
  onChangeDraft: (patch: Partial<ColumnDraft>) => void;
  onSaveSingle: () => void;
  onReset: () => void;
};

export function ColumnInspector({
  column,
  draft,
  writable,
  isDirty,
  savingSingle,
  foreignKeys,
  hasPrev,
  hasNext,
  onPrev,
  onNext,
  onClose,
  onChangeDraft,
  onSaveSingle,
  onReset,
}: ColumnInspectorProps) {
  const t = useTranslate();
  const { open } = useNotification();
  const isMobile = useMediaQuery("(max-width: 62em)") === true;
  const [pasteOpen, setPasteOpen] = useState(false);
  const [pasteRaw, setPasteRaw] = useState("");

  useEffect(() => {
    setPasteOpen(false);
    setPasteRaw("");
  }, [column?.id]);

  if (!column || !draft) return null;

  const copyLocator = async () => {
    try {
      await copyText(column.locator_key);
      open?.({ type: "success", message: t("common.copy.success") });
    } catch {
      open?.({ type: "error", message: t("common.copy.failed") });
    }
  };

  const applyBulkPaste = () => {
    const parsed = parseBulkEnumText(pasteRaw);
    if (parsed.length > 0) {
      onChangeDraft({
        enum_catalog: [...draft.enum_catalog, ...parsed],
      });
    }
    setPasteRaw("");
    setPasteOpen(false);
  };

  const header = (
    <Group
      justify="space-between"
      wrap="nowrap"
      px="sm"
      py="xs"
      style={{ borderBottom: "1px solid var(--refraq-tone-neutral-border)" }}
    >
      <Group gap="xs" wrap="nowrap" style={{ minWidth: 0 }}>
        <Badge size="xs" variant="light" color="gray">
          #{column.ordinal}
        </Badge>
        <Text size="sm" ff="monospace" fw={600} truncate>
          {column.name}
        </Text>
        {isDirty ? (
          <Badge size="xs" color="yellow">
            *
          </Badge>
        ) : null}
      </Group>
      <Group gap={4} wrap="nowrap">
        <Tooltip label={t("catalog.columns.prevColumn")}>
          <ActionIcon
            variant="subtle"
            size="sm"
            aria-label={t("catalog.columns.prevColumn")}
            disabled={!hasPrev}
            onClick={onPrev}
          >
            <ChevronUpIcon />
          </ActionIcon>
        </Tooltip>
        <Tooltip label={t("catalog.columns.nextColumn")}>
          <ActionIcon
            variant="subtle"
            size="sm"
            aria-label={t("catalog.columns.nextColumn")}
            disabled={!hasNext}
            onClick={onNext}
          >
            <ChevronDownIcon />
          </ActionIcon>
        </Tooltip>
        <Tooltip label={t("form.dialog.close")}>
          <ActionIcon
            variant="subtle"
            size="sm"
            aria-label={t("form.dialog.close")}
            onClick={onClose}
          >
            <CloseIcon />
          </ActionIcon>
        </Tooltip>
      </Group>
    </Group>
  );

  const body = (
    <Stack gap="md" p="sm">
      <Stack gap="xs">
        <Text size="xs" fw={600} c="dimmed" tt="uppercase">
          {t("catalog.structure.title")}
        </Text>
        <Group gap="xs" wrap="wrap">
          <Text size="xs" ff="monospace">
            {column.data_type}
          </Text>
          {column.normalized_type === "unknown" ? (
            <Badge size="xs" color="orange" variant="filled">
              {t("catalog.fields.normalizedTypeUnknown")}
            </Badge>
          ) : column.normalized_type ? (
            <Badge size="xs" variant="light" color="gray">
              {column.normalized_type}
            </Badge>
          ) : null}
          {!column.nullable ? (
            <Badge size="xs" variant="outline" color="gray">
              {t("catalog.columns.badgeNotNull")}
            </Badge>
          ) : null}
          {!column.is_present ? (
            <Badge size="xs" color="gray">
              {t("catalog.fields.absentValue")}
            </Badge>
          ) : null}
        </Group>

        {column.default_value ? (
          <Text size="xs" c="dimmed">
            {t("catalog.structure.default")}:{" "}
            <Text span ff="monospace" size="xs">
              {column.default_value}
            </Text>
          </Text>
        ) : null}

        {column.comment ? (
          <Text size="xs" c="dimmed">
            {t("catalog.fields.comment")}: {column.comment}
          </Text>
        ) : null}

        <Group gap="xs" wrap="nowrap">
          <Text size="xs" c="dimmed" ff="monospace" truncate>
            {column.locator_key}
          </Text>
          <ActionIcon
            variant="subtle"
            size="xs"
            aria-label={t("catalog.detail.locator")}
            onClick={() => void copyLocator()}
          >
            <CopyIcon size={12} />
          </ActionIcon>
        </Group>

        {foreignKeys.length > 0 ? (
          <Stack gap={4}>
            <Text size="xs" c="dimmed">
              {t("catalog.structure.foreignKeys")}:
            </Text>
            {foreignKeys.map((fk) => {
              const targetLabel = `${fk.ref_schema}.${fk.ref_table}(${fk.ref_columns.join(", ")})`;
              return fk.ref_object_id ? (
                <ConsoleLink
                  key={fk.name}
                  href={`/console/catalog/${fk.ref_object_id}`}
                >
                  <Text size="xs" ff="monospace">
                    {targetLabel}
                  </Text>
                </ConsoleLink>
              ) : (
                <Text key={fk.name} size="xs" ff="monospace">
                  {targetLabel}
                </Text>
              );
            })}
          </Stack>
        ) : null}

        {column.semantic_source ? (
          <Text size="xs" c="dimmed">
            {t("catalog.semantics.provenance")}:{" "}
            {semanticSourceLabel(t, column.semantic_source)}
          </Text>
        ) : null}
      </Stack>

      <Divider />

      <Stack gap="xs">
        <Text size="xs" fw={600} c="dimmed" tt="uppercase">
          {t("catalog.columns.semanticsHeader")}
        </Text>

        <TextField
          label={t("catalog.semantics.businessName")}
          size="xs"
          editable={writable}
          value={draft.business_name}
          onChange={(e) =>
            onChangeDraft({ business_name: e.currentTarget.value })
          }
        />

        <Stack gap={4}>
          <TextareaField
            label={t("catalog.semantics.businessDescription")}
            size="xs"
            editable={writable}
            minRows={2}
            value={draft.business_description}
            onChange={(e) =>
              onChangeDraft({ business_description: e.currentTarget.value })
            }
          />
          {writable && column.comment ? (
            <Button
              size="compact-xs"
              variant="subtle"
              w="fit-content"
              onClick={() =>
                onChangeDraft({ business_description: column.comment ?? "" })
              }
            >
              {t("catalog.columns.useComment")}
            </Button>
          ) : null}
        </Stack>

        <Stack gap={4}>
          <TextField
            label={t("catalog.semantics.semanticType")}
            size="xs"
            editable={writable}
            value={draft.column_semantics.semantic_type ?? ""}
            onChange={(e) =>
              onChangeDraft({
                column_semantics: {
                  ...draft.column_semantics,
                  semantic_type: e.currentTarget.value,
                },
              })
            }
          />
          {writable ? (
            <Stack gap={4}>
              <Text size="xs" c="dimmed">
                {t("catalog.columns.quickTypes")}
              </Text>
              <Group gap={4} wrap="wrap">
                {QUICK_SEMANTIC_TYPES.map((typeName) => {
                  const active =
                    draft.column_semantics.semantic_type === typeName;
                  return (
                    <Button
                      key={typeName}
                      size="compact-xs"
                      variant={active ? "filled" : "light"}
                      onClick={() =>
                        onChangeDraft({
                          column_semantics: {
                            ...draft.column_semantics,
                            semantic_type: active ? "" : typeName,
                          },
                        })
                      }
                    >
                      {typeName}
                    </Button>
                  );
                })}
              </Group>
            </Stack>
          ) : null}
        </Stack>

        <Group grow>
          <TextField
            label={t("catalog.semantics.unit")}
            size="xs"
            editable={writable}
            value={draft.column_semantics.unit ?? ""}
            onChange={(e) =>
              onChangeDraft({
                column_semantics: {
                  ...draft.column_semantics,
                  unit: e.currentTarget.value,
                },
              })
            }
          />
          <TextField
            label={t("catalog.semantics.valuePattern")}
            size="xs"
            editable={writable}
            value={draft.column_semantics.value_pattern ?? ""}
            onChange={(e) =>
              onChangeDraft({
                column_semantics: {
                  ...draft.column_semantics,
                  value_pattern: e.currentTarget.value,
                },
              })
            }
          />
        </Group>
      </Stack>

      <Divider />

      <Stack gap="xs">
        <Group justify="space-between" align="center">
          <Text size="xs" fw={600} c="dimmed" tt="uppercase">
            {t("catalog.columns.enumTitle")}
          </Text>
          {writable ? (
            <Button
              size="compact-xs"
              variant="subtle"
              onClick={() => setPasteOpen((prev) => !prev)}
            >
              {t("catalog.columns.enumPasteToggle")}
            </Button>
          ) : null}
        </Group>

        {writable && pasteOpen ? (
          <Stack gap="xs">
            <Textarea
              size="xs"
              minRows={3}
              placeholder={t("catalog.columns.enumPastePlaceholder")}
              value={pasteRaw}
              onChange={(e) => setPasteRaw(e.currentTarget.value)}
            />
            <Group gap="xs">
              <Button size="xs" variant="light" onClick={applyBulkPaste}>
                {t("catalog.columns.enumPasteApply")}
              </Button>
              <Button
                size="xs"
                variant="subtle"
                onClick={() => {
                  setPasteRaw("");
                  setPasteOpen(false);
                }}
              >
                {t("common.cancel")}
              </Button>
            </Group>
          </Stack>
        ) : null}

        {draft.enum_catalog.map((entry, idx) => (
          <Stack
            key={`${column.id}-enum-${idx}`}
            gap={4}
            p="xs"
            style={{
              border: "1px solid var(--refraq-tone-neutral-border)",
              borderRadius: "var(--mantine-radius-sm)",
            }}
          >
            <Group grow align="flex-end">
              <TextField
                label={t("catalog.columns.enumCode")}
                size="xs"
                editable={writable}
                value={entry.code}
                onChange={(e) => {
                  const next = [...draft.enum_catalog];
                  next[idx] = { ...entry, code: e.currentTarget.value };
                  onChangeDraft({ enum_catalog: next });
                }}
              />
              <TextField
                label={t("catalog.columns.enumLabel")}
                size="xs"
                editable={writable}
                value={entry.label}
                onChange={(e) => {
                  const next = [...draft.enum_catalog];
                  next[idx] = { ...entry, label: e.currentTarget.value };
                  onChangeDraft({ enum_catalog: next });
                }}
              />
            </Group>
            <Group align="flex-end" wrap="nowrap">
              <Box style={{ flex: 1 }}>
                <TextareaField
                  label={t("catalog.columns.enumDescription")}
                  size="xs"
                  editable={writable}
                  value={entry.description ?? ""}
                  minRows={1}
                  onChange={(e) => {
                    const next = [...draft.enum_catalog];
                    next[idx] = {
                      ...entry,
                      description: e.currentTarget.value,
                    };
                    onChangeDraft({ enum_catalog: next });
                  }}
                />
              </Box>
              {writable ? (
                <Button
                  size="xs"
                  variant="subtle"
                  color="red"
                  onClick={() => {
                    const next = draft.enum_catalog.filter((_, i) => i !== idx);
                    onChangeDraft({ enum_catalog: next });
                  }}
                >
                  {t("catalog.columns.enumRemove")}
                </Button>
              ) : null}
            </Group>
          </Stack>
        ))}

        {writable ? (
          <Button
            size="xs"
            variant="light"
            w="fit-content"
            leftSection={<PlusIcon size={14} />}
            onClick={() =>
              onChangeDraft({
                enum_catalog: [
                  ...draft.enum_catalog,
                  { code: "", label: "", description: "" },
                ],
              })
            }
          >
            {t("catalog.columns.enumAdd")}
          </Button>
        ) : null}
      </Stack>
    </Stack>
  );

  const footer = writable ? (
    <Group
      justify="space-between"
      px="sm"
      py="xs"
      style={{ borderTop: "1px solid var(--refraq-tone-neutral-border)" }}
    >
      <Button
        size="xs"
        loading={savingSingle}
        disabled={!isDirty}
        onClick={onSaveSingle}
      >
        {t("catalog.semantics.saveColumn")}
      </Button>
      {isDirty ? (
        <Button
          size="xs"
          variant="subtle"
          color="red"
          leftSection={<UndoIcon size={14} />}
          onClick={onReset}
        >
          {t("catalog.overview.resetDraft")}
        </Button>
      ) : null}
    </Group>
  ) : null;

  if (isMobile) {
    return (
      <Drawer
        opened
        onClose={onClose}
        position="right"
        size="lg"
        title={t("catalog.columns.inspectorTitle")}
      >
        <Stack gap={0} h="100%">
          {header}
          <ScrollArea flex={1}>{body}</ScrollArea>
          {footer}
        </Stack>
      </Drawer>
    );
  }

  return (
    <Paper
      withBorder
      w={420}
      miw={360}
      maw="100%"
      aria-label={t("catalog.columns.inspectorTitle")}
      style={{
        display: "flex",
        flexDirection: "column",
        height: "100%",
        minHeight: 0,
        flexShrink: 0,
      }}
    >
      {header}
      <ScrollArea flex={1} style={{ minHeight: 0 }}>
        {body}
      </ScrollArea>
      {footer}
    </Paper>
  );
}
