export type TokenMetadata = {
  id: string;
  name: string;
  prefix: string;
  expires_at: string;
  revoked_at: string | null;
  created_at: string;
  last_used_at: string | null;
};

export type TokenListResponse = {
  items: TokenMetadata[];
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
