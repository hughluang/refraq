"use client";

import { useState } from "react";
import { useTranslate } from "@refinedev/core";

import type { DatasetCapacity } from "@/features/channels/types";
import {
  formatCeilingGigabytes,
  formatDatasetGigabytes,
} from "@/features/channel-dataset-usage/gigabytes";

export function CapacityBar({ capacity }: { capacity: DatasetCapacity }) {
  const t = useTranslate();
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const open = hovered || focused;
  const used = capacity.used_bytes;
  const ceiling = capacity.ceiling_bytes;
  const fill = Math.min(used / ceiling, 1);
  const over = used > ceiling;
  const lines = [
    t("channelDatasetUsage.used", { used: formatDatasetGigabytes(used) }),
    t("channelDatasetUsage.ceiling", { ceiling: formatCeilingGigabytes(ceiling) }),
  ];
  if (over) lines.push(t("channelDatasetUsage.over"));
  lines.push(
    used >= ceiling
      ? t("channelDatasetUsage.refused")
      : t("channelDatasetUsage.remain", {
          remain: formatDatasetGigabytes(ceiling - used),
        }),
  );

  return (
    <div
      data-capacity-bar=""
      tabIndex={0}
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
      onFocus={() => setFocused(true)}
      onBlur={() => setFocused(false)}
      style={{ position: "relative" }}
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
      {open ? (
        <div data-capacity-tip="">
          {lines.map((line) => (
            <div key={line}>{line}</div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
