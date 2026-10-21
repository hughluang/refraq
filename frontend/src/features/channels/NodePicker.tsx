"use client";

import { Paper, Text, TextInput } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useId, useRef, useState } from "react";

import { familyTint, nodeTypeIcon } from "@/features/channels/nodeVisual";
import { nodeTypeLabel, nodeTypeSummary } from "@/features/channels/nodeTypeCopy";
import {
  filterNodeTypes,
  PICKER_MAX_HEIGHT,
  PICKER_WIDTH,
  pickerOrigin,
} from "@/features/channels/nodePicker";
import type { NodeTypeSpec } from "@/features/channels/types";

export type PickerEntry = {
  spec: NodeTypeSpec;
  disabled: boolean;
  reason: string;
};

function optionDomId(type: string): string {
  return `channel-picker-option-${type.replace(/[^A-Za-z0-9_-]/g, "-")}`;
}

function groupEntries(entries: readonly PickerEntry[]): { family: string; items: PickerEntry[] }[] {
  const groups: { family: string; items: PickerEntry[] }[] = [];
  const byFamily = new Map<string, PickerEntry[]>();
  for (const entry of entries) {
    const family = entry.spec.family;
    const items = byFamily.get(family);
    if (items) {
      items.push(entry);
      continue;
    }
    const created = [entry];
    byFamily.set(family, created);
    groups.push({ family, items: created });
  }
  return groups;
}

export function NodePicker({
  entries,
  anchor,
  frame,
  preferAbove,
  onSelect,
  onClose,
}: {
  entries: readonly PickerEntry[];
  anchor: { x: number; y: number };
  frame: { width: number; height: number };
  preferAbove: boolean;
  onSelect: (spec: NodeTypeSpec) => void;
  onClose: () => void;
}) {
  const t = useTranslate();
  const listId = useId();
  const inputRef = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState("");
  const [activeType, setActiveType] = useState<string | null>(null);
  const matched = new Set(
    filterNodeTypes(
      entries.map((entry) => entry.spec),
      query,
      t,
    ).map((spec) => spec.type),
  );
  const visible = entries.filter((entry) => matched.has(entry.spec.type));
  const visibleKey = visible.map((entry) => entry.spec.type).join("|");
  const groups = groupEntries(visible);
  const origin = pickerOrigin(anchor, frame, preferAbove);
  const activeId = activeType ? optionDomId(activeType) : undefined;

  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  useEffect(() => {
    if (!activeType) return;
    if (visibleKey.split("|").includes(activeType)) return;
    setActiveType(null);
  }, [activeType, visibleKey]);

  useEffect(() => {
    if (!activeType) return;
    const option = document.getElementById(optionDomId(activeType));
    if (option && typeof option.scrollIntoView === "function") {
      option.scrollIntoView({ block: "nearest" });
    }
  }, [activeType]);

  const move = (delta: number) => {
    const enabled = visible.filter((entry) => !entry.disabled);
    if (enabled.length === 0) {
      setActiveType(null);
      return;
    }
    const currentIndex = visible.findIndex((entry) => entry.spec.type === activeType);
    if (currentIndex < 0) {
      const next = delta > 0 ? enabled[0] : enabled[enabled.length - 1];
      setActiveType(next.spec.type);
      return;
    }
    let cursor = currentIndex;
    for (let step = 0; step < visible.length; step += 1) {
      cursor = (cursor + delta + visible.length) % visible.length;
      const entry = visible[cursor];
      if (entry && !entry.disabled) {
        setActiveType(entry.spec.type);
        return;
      }
    }
  };

  const chooseActive = () => {
    const entry = visible.find((item) => item.spec.type === activeType);
    if (!entry || entry.disabled) return;
    onSelect(entry.spec);
  };

  return (
    <Paper
      className="channel-node-picker"
      shadow="md"
      withBorder
      p="xs"
      style={{ left: origin.left, top: origin.top, width: PICKER_WIDTH, maxHeight: PICKER_MAX_HEIGHT }}
      onPointerDown={(event) => event.stopPropagation()}
    >
      <TextInput
        ref={inputRef}
        size="xs"
        value={query}
        placeholder={t("channels.canvas.searchNodes")}
        aria-label={t("channels.canvas.searchNodes")}
        aria-controls={visible.length > 0 ? listId : undefined}
        aria-activedescendant={activeId}
        aria-autocomplete="list"
        onChange={(event) => setQuery(event.currentTarget.value)}
        onKeyDown={(event) => {
          if (event.key === "ArrowDown") {
            event.preventDefault();
            move(1);
            return;
          }
          if (event.key === "ArrowUp") {
            event.preventDefault();
            move(-1);
            return;
          }
          if (event.key === "Enter") {
            event.preventDefault();
            chooseActive();
            return;
          }
          if (event.key === "Escape") {
            event.preventDefault();
            event.stopPropagation();
            onClose();
          }
        }}
      />
      {visible.length === 0 ? (
        <Text className="channel-node-picker__empty" size="sm" c="dimmed">
          {t("channels.canvas.searchEmpty")}
        </Text>
      ) : (
        <div
          id={listId}
          className="channel-node-picker__list"
          role="listbox"
          aria-label={t("channels.canvas.palette")}
          aria-activedescendant={activeId}
        >
          {groups.map((group) => (
            <div key={group.family}>
              <Text className="channel-node-picker__family" size="xs" fw={600} c="dimmed">
                {t(`channels.canvas.family.${group.family}`, { defaultValue: group.family })}
              </Text>
              {group.items.map((entry) => {
                const TypeIcon = nodeTypeIcon(entry.spec.type, entry.spec.family);
                const selected = entry.spec.type === activeType;
                return (
                  <div
                    key={entry.spec.type}
                    id={optionDomId(entry.spec.type)}
                    role="option"
                    aria-selected={selected}
                    aria-disabled={entry.disabled || undefined}
                    className="channel-node-picker__option"
                    onMouseEnter={() => setActiveType(entry.spec.type)}
                    onClick={() => {
                      if (entry.disabled) return;
                      onSelect(entry.spec);
                    }}
                  >
                    <span
                      className={`channel-flow-node__icon channel-node-picker__icon channel-flow-node__icon--${familyTint(entry.spec.family)}`}
                      aria-hidden
                    >
                      <TypeIcon size={16} />
                    </span>
                    <span className="channel-node-picker__copy">
                      <span className="channel-node-picker__label">{nodeTypeLabel(t, entry.spec)}</span>
                      <span className="channel-node-picker__summary">{nodeTypeSummary(t, entry.spec)}</span>
                      {entry.reason ? (
                        <span className="channel-node-picker__summary">{entry.reason}</span>
                      ) : null}
                    </span>
                  </div>
                );
              })}
            </div>
          ))}
        </div>
      )}
    </Paper>
  );
}
