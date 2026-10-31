"use client";

import { Alert } from "@mantine/core";
import type { ReactNode } from "react";

export type CalloutTone = "info" | "notice";

type CalloutProps = {
  tone: CalloutTone;
  title?: ReactNode;
  children?: ReactNode;
};

/** Notice uses the yellow theme token. */
const TONE_COLOR: Record<CalloutTone, string> = {
  info: "var(--refraq-tone-info)",
  notice: "var(--refraq-tone-warning)",
};

export function Callout({ tone, title, children }: CalloutProps) {
  return (
    <Alert
      role="group"
      variant="light"
      color={TONE_COLOR[tone]}
      withCloseButton={false}
      title={title}
    >
      {children}
    </Alert>
  );
}
