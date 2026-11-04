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
  const ratio = used / ceiling;
  const fill = Math.min(ratio, 1);
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
        data-capacity-track=""
        style={{
          position: "relative",
          height: 12,
          background: "var(--refraq-tone-neutral-muted)",
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
        {over ? (
          <div
            data-capacity-over=""
            style={{
              position: "absolute",
              left: "100%",
              top: 0,
              height: "100%",
              width: `${((used - ceiling) / ceiling) * 100}%`,
              background: "var(--refraq-tone-danger)",
            }}
          />
        ) : null}
        <div
          data-capacity-tick=""
          style={{
            position: "absolute",
            left: "100%",
            top: -4,
            bottom: -4,
            width: 2,
            background: "var(--mantine-color-text)",
          }}
        />
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
