import type { Instant } from "@/lib/instant";

export type TokenMetadata = {
  id: string;
  name: string;
  prefix: string;
  expires_at: Instant;
  revoked_at: Instant | null;
  created_at: Instant;
  last_used_at: Instant | null;
};

export type CreateTokenRequest = {
  name: string;
  expires_at: string;
};

export type CreateTokenResponse = {
  token: TokenMetadata;
  secret: string;
};

export type TokenStatus = "active" | "expired" | "deactivated";
