export type NormalizedType =
  | "string"
  | "integer"
  | "number"
  | "boolean"
  | "date"
  | "timestamp"
  | "time"
  | "interval"
  | "binary"
  | "json"
  | "array"
  | "unknown";

export type EntityAttribute = {
  name: string;
  normalized_type: NormalizedType;
  nullable: boolean;
  unique: boolean;
  indexed: boolean;
  description: string | null;
};

export type AttributeDraft = {
  name: string;
  normalized_type: NormalizedType;
  nullable: boolean;
  unique: boolean;
  indexed: boolean;
  description: string;
};

export type Alignment = {
  table_present: boolean;
  definition_ahead: boolean;
  latest_job_id: string | null;
  latest_job_status: string | null;
};

export type PublishStatus = "unpublished" | "publishing" | "published";

export type CurrentVersionSummary = {
  id: string;
  version: number;
  publish_status: PublishStatus;
  table_name: string | null;
  alignment: Alignment;
};

export type BusinessEntity = {
  id: string;
  table_name: string;
  name: string;
  description: string;
  deprecated_at: string | null;
  ever_published: boolean;
  current_version: CurrentVersionSummary | null;
  created_at: string;
  updated_at: string;
};

export type EntityVersion = {
  id: string;
  entity_id: string;
  version: number;
  publish_status: PublishStatus;
  attributes?: EntityAttribute[];
  attribute_count?: number;
  table_name: string | null;
  alignment: Alignment;
  created_at: string;
  updated_at: string;
};

export type EntityCreate = {
  table_name: string;
  name: string;
  description: string;
  attributes: EntityAttribute[];
};

export type EntityPatch = {
  name?: string;
  description?: string;
  attributes?: EntityAttribute[];
};

export type ShapeWrite = {
  attributes?: EntityAttribute[];
};

export type EntityJobEnqueue = {
  job: {
    id: string;
    kind: string;
    status: string;
  } | null;
  version: EntityVersion | null;
};
