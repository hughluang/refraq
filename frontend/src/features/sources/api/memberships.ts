import { apiClient } from "@/lib/api";
import type { MembershipWrite, SourceMembership } from "@/features/sources/membership";

export function listSourceMemberships(sourceId: string) {
  return apiClient<{ items: SourceMembership[] }>(`/sources/${sourceId}/memberships`);
}

export function createSourceMembership(sourceId: string, body: MembershipWrite) {
  return apiClient<{ membership: SourceMembership }>(`/sources/${sourceId}/memberships`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function changeSourceMembership(sourceId: string, membershipId: string, level: string) {
  return apiClient<{ membership: SourceMembership }>(
    `/sources/${sourceId}/memberships/${membershipId}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ level }),
    },
  );
}

export function deleteSourceMembership(sourceId: string, membershipId: string) {
  return apiClient<void>(`/sources/${sourceId}/memberships/${membershipId}`, {
    method: "DELETE",
  });
}

export function listEverySourceMemberships() {
  return apiClient<{ items: SourceMembership[] }>("/source-memberships");
}

export function createEverySourceMembership(body: MembershipWrite) {
  return apiClient<{ membership: SourceMembership }>("/source-memberships", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function changeEverySourceMembership(membershipId: string, level: string) {
  return apiClient<{ membership: SourceMembership }>(`/source-memberships/${membershipId}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ level }),
  });
}

export function deleteEverySourceMembership(membershipId: string) {
  return apiClient<void>(`/source-memberships/${membershipId}`, { method: "DELETE" });
}
