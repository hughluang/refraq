"use client";

import { StatusBadge } from "@/components/display/StatusBadge";
import { presentJobStatus } from "@/components/display/statusTone";

type Props = {
  status: string;
};

export function JobStatusBadge({ status }: Props) {
  const presentation = presentJobStatus(status);
  return <StatusBadge tone={presentation.tone} labelKey={presentation.labelKey} />;
}
