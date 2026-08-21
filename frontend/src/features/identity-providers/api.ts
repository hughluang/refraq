import { apiClient } from "@/lib/api";
import type { OffsetPage, PageQuery } from "@/lib/pagination";
import type {
  ClaimPendingBody,
  IdentityProvider,
  IdentityProviderProtocol,
  IdentityProviderSpec,
  IdentityProviderTestResult,
  IdentityProviderWrite,
  PendingFederatedIdentity,
} from "@/features/identity-providers/types";

function pageSuffix(params?: PageQuery): string {
  const qs = new URLSearchParams();
  if (params?.limit != null) qs.set("limit", String(params.limit));
  if (params?.offset != null) qs.set("offset", String(params.offset));
  const query = qs.toString();
  return query ? `?${query}` : "";
}

export function listIdentityProviders(params?: PageQuery) {
  return apiClient<OffsetPage<IdentityProvider>>(
    `/identity-providers${pageSuffix(params)}`,
  );
}

export function getIdentityProvider(id: string) {
  return apiClient<{ provider: IdentityProvider }>(`/identity-providers/${id}`);
}

export function getIdentityProviderSpec(
  protocol: IdentityProviderProtocol = "oidc",
) {
  return apiClient<{
    protocol: IdentityProviderProtocol;
    spec: IdentityProviderSpec;
  }>(`/identity-providers/spec?protocol=${encodeURIComponent(protocol)}`);
}

export function createIdentityProvider(body: IdentityProviderWrite) {
  return apiClient<{ provider: IdentityProvider }>("/identity-providers", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function patchIdentityProvider(
  id: string,
  body: Partial<IdentityProviderWrite>,
  options?: { disableBoundUsers?: boolean },
) {
  const qs = options?.disableBoundUsers ? "?disable_bound_users=true" : "";
  return apiClient<{ provider: IdentityProvider }>(
    `/identity-providers/${id}${qs}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

export function testIdentityProvider(id: string) {
  return apiClient<IdentityProviderTestResult>(
    `/identity-providers/${id}/test`,
    { method: "POST" },
  );
}

export function deleteIdentityProvider(
  id: string,
  disableBoundUsers = false,
) {
  const qs = disableBoundUsers ? "?disable_bound_users=true" : "";
  return apiClient<{ bound_user_count: number }>(
    `/identity-providers/${id}${qs}`,
    { method: "DELETE" },
  );
}

export function listPendingFederatedIdentities(params?: PageQuery) {
  return apiClient<OffsetPage<PendingFederatedIdentity>>(
    `/users/pending-federated-identities${pageSuffix(params)}`,
  );
}

export function claimPendingFederatedIdentity(
  id: string,
  body: ClaimPendingBody,
) {
  return apiClient<{ user: { id: string } }>(
    `/users/pending-federated-identities/${id}/claim`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

export function unfederateUser(id: string, password: string) {
  return apiClient<{ user: { id: string } }>(`/users/${id}/unfederate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ password }),
  });
}
