"use client";

import { Stack, Text, Tooltip } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useState } from "react";

import type { DatasetCapacity } from "@/features/channels/types";
import {
  formatCeilingGigabytes,
  formatDatasetGigabytes,
} from "@/features/channel-dataset-usage/gigabytes";

import "./CapacityBar.css";

export function CapacityBar({ capacity }: { capacity: DatasetCapacity }) {
  const t = useTranslate();
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const open = hovered || focused;
  const used = capacity.used_bytes;
  const ceiling = capacity.ceiling_bytes;
  const fill = Math.min(used / ceiling, 1);
  const over = used > ceiling;
  const usedLine = t("channelDatasetUsage.used", { used: formatDatasetGigabytes(used) });
  const ceilingLine = t("channelDatasetUsage.ceiling", {
    ceiling: formatCeilingGigabytes(ceiling),
  });
  const policy =
    used >= ceiling
      ? t("channelDatasetUsage.refused")
      : t("channelDatasetUsage.remain", {
          remain: formatDatasetGigabytes(ceiling - used),
        });

  return (
    <Tooltip
      opened={open}
      events={{ hover: false, focus: false, touch: false }}
      withinPortal
      withArrow
      position="bottom-start"
      multiline
      maw={360}
      label={
        <Stack gap={4} data-capacity-tip="">
          <Text size="xs">{usedLine}</Text>
          <Text size="xs">{ceilingLine}</Text>
          {over ? (
            <Text size="xs" style={{ color: "var(--refraq-tone-danger)" }}>
              {t("channelDatasetUsage.over")}
            </Text>
          ) : null}
          <Text size="xs" data-capacity-policy="">
            {policy}
          </Text>
        </Stack>
      }
    >
      <div
        data-capacity-bar=""
        tabIndex={0}
        onMouseEnter={() => setHovered(true)}
        onMouseLeave={() => setHovered(false)}
        onFocus={() => setFocused(true)}
        onBlur={() => setFocused(false)}
      >
        <div
          style={{
            display: "flex",
            height: 12,
            background: "var(--refraq-tone-neutral-muted)",
          }}
        >
          <div
            data-capacity-track=""
            style={{
              flexGrow: ceiling,
              flexShrink: 0,
              flexBasis: 0,
              minWidth: 0,
              height: "100%",
            }}
          >
            <div
              data-capacity-fill=""
              style={{
                width: `${fill * 100}%`,
                height: "100%",
                background: "var(--refraq-tone-success)",
              }}
            />
          </div>
          <div
            data-capacity-tick=""
            style={{
              flexGrow: 0,
              flexShrink: 0,
              flexBasis: 2,
              height: "100%",
              background: "var(--mantine-color-text)",
            }}
          />
          {over ? (
            <div
              data-capacity-over=""
              style={{
                flexGrow: used - ceiling,
                flexShrink: 0,
                flexBasis: 0,
                minWidth: 0,
                height: "100%",
                background: "var(--refraq-tone-danger)",
              }}
            />
          ) : null}
        </div>
      </div>
    </Tooltip>
  );
}
