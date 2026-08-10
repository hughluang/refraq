import { apiClient } from "@/lib/api";

import type {
  BusinessDomain,
  BusinessDomainCreate,
  BusinessDomainPatch,
} from "./types";

export function listBusinessDomains(params?: {
  q?: string;
  limit?: number;
  offset?: number;
}) {
  const qs = new URLSearchParams();
  if (params?.q) qs.set("q", params.q);
  if (params?.limit != null) qs.set("limit", String(params.limit));
  if (params?.offset != null) qs.set("offset", String(params.offset));
  const suffix = qs.toString() ? `?${qs.toString()}` : "";
  return apiClient<{
    items: BusinessDomain[];
    total: number;
    limit: number;
    offset: number;
  }>(`/business-domains${suffix}`);
}

export function createBusinessDomain(body: BusinessDomainCreate) {
  return apiClient<{ domain: BusinessDomain }>("/business-domains", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function patchBusinessDomain(id: string, body: BusinessDomainPatch) {
  return apiClient<{ domain: BusinessDomain }>(`/business-domains/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function deleteBusinessDomain(id: string) {
  return apiClient<void>(`/business-domains/${id}`, { method: "DELETE" });
}
