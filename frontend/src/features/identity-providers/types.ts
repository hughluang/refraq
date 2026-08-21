import type { JsonSchemaProperty } from "@/lib/json-schema";

export type IdentityProviderProtocol = "oidc";

export type IdentityProvider = {
  id: string;
  protocol: IdentityProviderProtocol;
  display_name: string;
  issuer: string;
  enabled: boolean;
  auto_provision: boolean;
  group_claim: string;
  group_allowlist: string[];
  default_role_id: string | null;
  scopes: string[];
  client_id: string;
  client_secret_configured: boolean;
  bound_user_count: number;
  updated_at: string | null;
};

export type IdentityProviderSpec = {
  $id?: string;
  title?: string;
  required?: string[];
  properties?: Record<string, JsonSchemaProperty>;
};

export type IdentityProviderFormValues = {
  display_name: string;
  protocol: IdentityProviderProtocol;
  enabled: boolean;
  issuer: string;
  client_id: string;
  client_secret: string;
  scopes: string;
  auto_provision: boolean;
  group_claim: string;
  group_allowlist: string;
  default_role_id: string | null;
};

export type IdentityProviderWrite = {
  protocol?: IdentityProviderProtocol;
  display_name: string;
  enabled: boolean;
  issuer?: string;
  client_id: string;
  client_secret?: string;
  scopes?: string[];
  auto_provision: boolean;
  group_claim?: string;
  group_allowlist?: string[];
  default_role_id?: string | null;
};

export type IdentityProviderTestResult = {
  issuer: string;
  authorization_endpoint: string;
  token_endpoint: string;
  jwks_uri: string;
  authorization_response_iss_parameter_supported: boolean;
  group_claim: string;
};

export type PublicAuthProvider = {
  id: string;
  display_name: string;
  protocol: IdentityProviderProtocol;
};

export type PendingFederatedIdentity = {
  id: string;
  issuer: string;
  account_hint: string;
  display_name: string | null;
  email: string | null;
  groups: string[];
  admission_reason: string;
  attempt_count: number;
  first_seen_at: string;
  last_attempt_at: string;
  expires_at: string;
  subject: string;
  provider_id: string | null;
};

export type ClaimPendingBody =
  | { user_id: string }
  | {
      create_user: {
        account: string;
        display_name: string;
        email: string | null;
        role_id: string;
      };
    };
