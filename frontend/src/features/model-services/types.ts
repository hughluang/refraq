export type ModelServicePurpose = "embedding";
export type ModelServiceProtocol = "openai_compat";
export type RebuildChoice = "none" | "full";
export type IndexStatus = "none" | "indexing" | "ready" | "failed";

export type ModelService = {
  id: string;
  purpose: ModelServicePurpose;
  protocol: ModelServiceProtocol;
  display_name: string;
  url: string;
  model: string;
  has_secret: boolean;
  in_use: boolean;
  created_at: string;
  updated_at: string;
};

export type PurposeState = {
  purpose: ModelServicePurpose;
  closed: boolean;
  ready: boolean;
  in_use_id: string | null;
  generation: number;
  index_status: IndexStatus;
};

export type ModelServiceFormValues = {
  display_name: string;
  url: string;
  model: string;
  api_key: string;
  clear_api_key: boolean;
};

export type ModelServiceWrite = {
  purpose?: ModelServicePurpose;
  protocol?: ModelServiceProtocol;
  display_name?: string;
  url?: string;
  model?: string;
  api_key?: string;
  clear_api_key?: boolean;
};

export type ModelServiceTestResult = {
  ok: boolean;
  dimension: number;
  elapsed_ms: number;
  model: string;
};
