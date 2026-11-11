import { apiClient } from "@/lib/api";
import type { HostRead, HostSpan } from "@/features/host/types";

export function readHost(span: HostSpan) {
  const params = new URLSearchParams({ span });
  return apiClient<HostRead>(`/host?${params.toString()}`);
}
