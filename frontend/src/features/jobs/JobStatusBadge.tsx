"use client";

import { StatusBadge, type StatusFreshness } from "@/components/display/StatusBadge";
import { presentJobStatus } from "@/components/display/statusTone";

type Props = {
  status: string;
  freshness?: StatusFreshness | null;
};

export function JobStatusBadge({ status, freshness }: Props) {
  const presentation = presentJobStatus(status);
  return (
    <StatusBadge
      tone={presentation.tone}
      labelKey={presentation.labelKey}
      freshness={freshness}
    />
  );
}
