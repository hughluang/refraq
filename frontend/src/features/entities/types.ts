import type { AttributeType } from "@/features/entities/attributeTypes.generated";

export type { AttributeType };

export type DictionaryRef = {
  id: string;
  name: string;
  display_name: string;
  deprecated: boolean;
};

export type AttributeConfig = {
  max_length?: number;
  precision?: number;
  scale?: number;
  dictionary_id?: string;
  target_entity_id?: string;
};

export type ReferenceTarget = {
  entity_id: string;
  name: string;
  table_name: string;
  business_key: string | null;
};

export type EntityAttribute = {
  name: string;
  type: AttributeType;
  required: boolean;
  unique: boolean;
  indexed: boolean;
  business_key: boolean;
  description: string | null;
  config: AttributeConfig;
  target?: ReferenceTarget | null;
  dictionary?: DictionaryRef | null;
  behind?: boolean;
};

export type EntityRecordFormValues = {
  table_name: string;
  name: string;
  description: string;
  attributes: AttributeDraft[];
};

export type AttributeDraft = {
  type: AttributeType;
  name: string;
  required: boolean;
  unique: boolean;
  indexed: boolean;
  business_key: boolean;
  description: string;
  max_length: string;
  precision: string;
  scale: string;
  dictionary_id: string;
  dictionary_name: string;
  dictionary_display_name: string;
  dictionary_deprecated: boolean;
  behind: boolean;
  target_entity_id: string;
  target_name: string;
  target_table_name: string;
};

export type InboundReference = {
  entity_id: string;
  table_name: string;
  attribute_name: string;
};

export type Alignment = {
  table_present: boolean;
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
  inbound_references?: InboundReference[];
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
