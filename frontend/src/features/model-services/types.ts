export type ModelServicePurpose = "embedding";
export type ModelServiceProtocol = "openai_compat";
export type IndexStatus = "none" | "indexing" | "ready" | "failed";

export type EmbedSchedule = {
  id: string;
  enabled: boolean;
  cron: string | null;
  interval_seconds: number | null;
  next_run_at: string | null;
};

export type ModelService = {
  id: string;
  purpose: ModelServicePurpose;
  protocol: ModelServiceProtocol;
  display_name: string;
  url: string;
  model: string;
  timeout_sec: number;
  batch_limit: number;
  has_secret: boolean;
  in_use: boolean;
  created_at: string;
  updated_at: string;
};

export type CatalogIndexCoverage = {
  objects_written: number;
  columns_written: number;
  objects_failed: number;
  columns_failed: number;
  objects_attempted: number;
  columns_attempted: number;
};

export type CatalogIndexState = {
  ready: boolean;
  generation_last_swept: number | null;
  index_status: IndexStatus;
  coverage: CatalogIndexCoverage;
  progress: string | null;
  failure_summary: string | null;
  rebuild_owed: boolean;
};

export type PurposeState = {
  purpose: ModelServicePurpose;
  closed: boolean;
  ready: boolean;
  in_use_id: string | null;
  generation: number;
  index_status: IndexStatus;
  catalog_index: CatalogIndexState;
  embed_schedule: EmbedSchedule | null;
};

export type ModelServiceFormValues = {
  display_name: string;
  url: string;
  model: string;
  timeout_sec: number;
  batch_limit: number;
  api_key: string;
  clear_api_key: boolean;
};

export type ModelServiceWrite = {
  purpose?: ModelServicePurpose;
  protocol?: ModelServiceProtocol;
  display_name?: string;
  url?: string;
  model?: string;
  timeout_sec?: number;
  batch_limit?: number;
  api_key?: string;
  clear_api_key?: boolean;
};

export type ModelServiceTestResult = {
  ok: boolean;
  dimension: number;
  elapsed_ms: number;
  model: string;
  output_dim: number;
  timeout_sec: number;
};
