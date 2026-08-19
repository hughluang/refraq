import { apiClient } from "@/lib/api";
import type { SampleRequestBody, SampleResult } from "@/features/sources/types";

export function runObjectSample(objectId: string, body: SampleRequestBody) {
  return apiClient<SampleResult>(`/objects/${objectId}/sample`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}
