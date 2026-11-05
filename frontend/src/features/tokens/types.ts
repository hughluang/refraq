export type TokenMetadata = {
  id: string;
  name: string;
  prefix: string;
  expires_at: string | null;
  revoked_at: string | null;
  created_at: string;
  last_used_at: string | null;
};

export type CreateTokenRequest = {
  name: string;
  expires_at: string | null;
};

export type CreateTokenResponse = {
  token: TokenMetadata;
  secret: string;
};

export type TokenStatus = "active" | "expired" | "deactivated";
