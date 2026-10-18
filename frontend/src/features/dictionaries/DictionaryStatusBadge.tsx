"use client";

import { StatusBadge } from "@/components/display/StatusBadge";
import { presentDictionaryStatus } from "@/components/display/statusTone";

type Props = {
  deprecated: boolean;
};

export function DictionaryStatusBadge({ deprecated }: Props) {
  const presentation = presentDictionaryStatus(deprecated);
  return <StatusBadge tone={presentation.tone} labelKey={presentation.labelKey} />;
}
