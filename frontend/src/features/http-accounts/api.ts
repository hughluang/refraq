import { apiClient } from "@/lib/api";
import type { OffsetPage } from "@/lib/pagination";

import type { HttpAccount, HttpAccountWrite } from "@/features/http-accounts/types";

function querySuffix(params?: Record<string, string | number | undefined>) {
  const qs = new URLSearchParams();
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === "") continue;
      qs.set(key, String(value));
    }
  }
  const encoded = qs.toString();
  return encoded ? `?${encoded}` : "";
}

export function listHttpAccounts(params?: { q?: string; limit?: number; offset?: number }) {
  return apiClient<OffsetPage<HttpAccount>>(`/http-accounts${querySuffix(params)}`);
}

export function getHttpAccount(id: string) {
  return apiClient<{ http_account: HttpAccount }>(`/http-accounts/${id}`);
}

export function createHttpAccount(body: HttpAccountWrite) {
  return apiClient<{ http_account: HttpAccount }>("/http-accounts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function patchHttpAccount(id: string, body: Partial<HttpAccountWrite>) {
  return apiClient<{ http_account: HttpAccount }>(`/http-accounts/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function deleteHttpAccount(id: string) {
  return apiClient<void>(`/http-accounts/${id}`, { method: "DELETE" });
}
