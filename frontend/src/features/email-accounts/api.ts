import { apiClient } from "@/lib/api";
import type { OffsetPage } from "@/lib/pagination";

import type {
  EmailAccount,
  EmailAccountTestResult,
  EmailAccountWrite,
} from "@/features/email-accounts/types";

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

export function listEmailAccounts(params?: { q?: string; limit?: number; offset?: number }) {
  return apiClient<OffsetPage<EmailAccount>>(`/email-accounts${querySuffix(params)}`);
}

export function getEmailAccount(id: string) {
  return apiClient<{ email_account: EmailAccount }>(`/email-accounts/${id}`);
}

export function createEmailAccount(body: EmailAccountWrite) {
  return apiClient<{ email_account: EmailAccount }>("/email-accounts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function patchEmailAccount(id: string, body: Partial<EmailAccountWrite>) {
  return apiClient<{ email_account: EmailAccount }>(`/email-accounts/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function deleteEmailAccount(id: string) {
  return apiClient<void>(`/email-accounts/${id}`, { method: "DELETE" });
}

export function testEmailAccount(id: string, to: string) {
  return apiClient<EmailAccountTestResult>(`/email-accounts/${id}/test`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ to }),
  });
}
