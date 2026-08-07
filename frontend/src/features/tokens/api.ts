import { apiClient } from "@/lib/api";
import type {
  CreateTokenRequest,
  CreateTokenResponse,
  TokenListResponse,
  TokenMetadata,
} from "@/features/tokens/types";

export function listTokens() {
  return apiClient<TokenListResponse>("/tokens");
}

export function createToken(body: CreateTokenRequest) {
  return apiClient<CreateTokenResponse>("/tokens", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export async function deactivateToken(id: string) {
  const data = await apiClient<{ token: TokenMetadata }>(
    `/tokens/${id}/deactivate`,
    { method: "POST" },
  );
  return data.token;
}

export async function restoreToken(id: string) {
  const data = await apiClient<{ token: TokenMetadata }>(
    `/tokens/${id}/restore`,
    { method: "POST" },
  );
  return data.token;
}

export function deleteToken(id: string) {
  return apiClient<void>(`/tokens/${id}`, { method: "DELETE" });
}
