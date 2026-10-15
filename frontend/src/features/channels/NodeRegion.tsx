"use client";

import { Text } from "@mantine/core";
import { useId, type ReactNode } from "react";

type Props = {
  title: string;
  tone?: "config" | "run";
  action?: ReactNode;
  children: ReactNode;
};

export function NodeRegion({ title, tone = "config", action, children }: Props) {
  const titleId = useId();
  return (
    <section
      className={`channel-node-region channel-node-region--${tone}`}
      aria-labelledby={titleId}
    >
      <div className="channel-node-region__title">
        <Text id={titleId} size="sm" fw={600}>
          {title}
        </Text>
        {action}
      </div>
      <div className="channel-node-region__body">{children}</div>
    </section>
  );
}
