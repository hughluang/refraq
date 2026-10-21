"use client";

import { Modal, Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";

export type ShortcutGroup = "edit" | "view";

export type ShortcutChord = {
  key: string;
  mod?: boolean;
  shift?: boolean;
};

export type CanvasShortcut = {
  id: string;
  group: ShortcutGroup;
  labelKey: string;
  chords: readonly ShortcutChord[];
};

export const CANVAS_SHORTCUTS: readonly CanvasShortcut[] = [
  {
    id: "undo",
    group: "edit",
    labelKey: "channels.canvas.undo",
    chords: [{ mod: true, key: "Z" }],
  },
  {
    id: "redo",
    group: "edit",
    labelKey: "channels.canvas.redo",
    chords: [
      { mod: true, shift: true, key: "Z" },
      { mod: true, key: "Y" },
    ],
  },
  {
    id: "delete",
    group: "edit",
    labelKey: "channels.canvas.shortcuts.delete",
    chords: [{ key: "Delete" }, { key: "Backspace" }],
  },
  {
    id: "open",
    group: "edit",
    labelKey: "channels.canvas.shortcuts.open",
    chords: [{ key: "Enter" }],
  },
  {
    id: "close",
    group: "edit",
    labelKey: "channels.canvas.shortcuts.close",
    chords: [{ key: "Escape" }],
  },
  {
    id: "fit",
    group: "view",
    labelKey: "channels.canvas.fitView",
    chords: [{ shift: true, key: "1" }],
  },
  {
    id: "zoomIn",
    group: "view",
    labelKey: "channels.canvas.zoomIn",
    chords: [{ mod: true, key: "=" }],
  },
  {
    id: "zoomOut",
    group: "view",
    labelKey: "channels.canvas.zoomOut",
    chords: [{ mod: true, key: "-" }],
  },
  {
    id: "zoom100",
    group: "view",
    labelKey: "channels.canvas.zoom100",
    chords: [{ mod: true, key: "0" }],
  },
  {
    id: "help",
    group: "view",
    labelKey: "channels.canvas.shortcuts.help",
    chords: [{ key: "?" }],
  },
];

const GROUP_ORDER: readonly ShortcutGroup[] = ["edit", "view"];

const GROUP_LABEL: Record<ShortcutGroup, string> = {
  edit: "channels.canvas.shortcuts.group.edit",
  view: "channels.canvas.shortcuts.group.view",
};

export function formatShortcutChord(chord: ShortcutChord, command: boolean): string {
  if (command) {
    const parts: string[] = [];
    if (chord.shift) parts.push("⇧");
    if (chord.mod) parts.push("⌘");
    parts.push(chord.key);
    return parts.join("");
  }
  const parts: string[] = [];
  if (chord.mod) parts.push("Ctrl");
  if (chord.shift) parts.push("Shift");
  parts.push(chord.key);
  return parts.join("+");
}

export function CanvasShortcuts({
  opened,
  onClose,
  userAgent,
}: {
  opened: boolean;
  onClose: () => void;
  userAgent: string;
}) {
  const t = useTranslate();
  const command = /Mac|iPhone|iPad|iPod/.test(userAgent);
  const groups = GROUP_ORDER.map((group) => ({
    group,
    rows: CANVAS_SHORTCUTS.filter((row) => row.group === group),
  }));

  return (
    <Modal
      opened={opened}
      onClose={onClose}
      title={t("channels.canvas.shortcuts")}
      closeOnEscape
    >
      <Stack gap="sm">
        {groups.map((section) => (
          <Stack key={section.group} gap={4}>
            <Text size="sm" fw={600}>
              {t(GROUP_LABEL[section.group])}
            </Text>
            {section.rows.map((row) => (
              <Text key={row.id} size="sm">
                {t(row.labelKey)}{" "}
                {row.chords.map((chord) => formatShortcutChord(chord, command)).join(" / ")}
              </Text>
            ))}
          </Stack>
        ))}
      </Stack>
    </Modal>
  );
}
