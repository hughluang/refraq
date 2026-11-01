export type InboundCredentialType = "token" | "hmac_sha256";

export type TokenLocation = "header" | "query";

export type HmacEncoding = "hex" | "base64";

export type TokenConfig = {
  location: TokenLocation;
  name: string;
};

export type HmacConfig = {
  signature_header: string;
  encoding: HmacEncoding;
  prefix?: string;
  timestamp_header?: string;
};

export type InboundCredentialConfig = TokenConfig | HmacConfig;

export type InboundCredential = {
  id: string;
  name: string;
  type: InboundCredentialType;
  config: InboundCredentialConfig;
  created_at: string;
  updated_at: string;
};

export type InboundCredentialCreate = {
  name: string;
  type: InboundCredentialType;
  secret: string;
  config: InboundCredentialConfig;
};

export type InboundCredentialPatch = {
  name?: string;
  type?: InboundCredentialType;
  secret?: string;
  config?: InboundCredentialConfig;
};
