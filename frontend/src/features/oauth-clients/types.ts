export type OAuthAuthMethod =
  | "private_key_jwt"
  | "client_secret_basic"
  | "client_secret_post";

export type OAuthClient = {
  id: string;
  client_id: string;
  name: string;
  description: string | null;
  provider_id: string;
  enabled: boolean;
  token_endpoint_auth_method: OAuthAuthMethod;
  jwks: Record<string, unknown> | null;
  jwks_uri: string | null;
  secret_prefix: string | null;
  client_secret_configured: boolean;
  allowed_grant_types: string[];
  allowed_subject_audiences: string[];
  allowed_surfaces: string[];
  allowed_scopes: string[];
  token_ttl_sec: number | null;
  created_at: string;
  updated_at: string;
  last_used_at: string | null;
};

export type OAuthClientWrite = {
  name: string;
  description?: string | null;
  provider_id?: string;
  enabled: boolean;
  token_endpoint_auth_method: OAuthAuthMethod;
  jwks?: Record<string, unknown> | null;
  jwks_uri?: string | null;
  allowed_grant_types: string[];
  allowed_subject_audiences: string[];
  allowed_surfaces: string[];
  allowed_scopes: string[];
  token_ttl_sec?: number | null;
};
