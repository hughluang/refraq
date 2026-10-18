"use client";

import { StatusBadge } from "@/components/display/StatusBadge";
import { presentStructureDiffClass } from "@/components/display/statusTone";

type Props = {
  value: string | null | undefined;
};

export function StructureDiffClassBadge({ value }: Props) {
  if (!value) return null;
  const presentation = presentStructureDiffClass(value);
  return <StatusBadge tone={presentation.tone} labelKey={presentation.labelKey} />;
}
