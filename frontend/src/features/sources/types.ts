import type { JsonSchemaProperty } from "@/lib/json-schema";

export type { JsonSchemaProperty };

export type Engine = "postgresql" | "mssql" | "oracle";

export type SourceAccess = Record<string, unknown>;

export type ConnectorSpec = {
  $id?: string;
  title?: string;
  type?: string;
  required?: string[];
  additionalProperties?: boolean;
  properties?: Record<string, JsonSchemaProperty>;
};

export type Source = {
  id: string;
  key: string;
  locator_key: string;
  name: string;
  kind: string;
  status: string;
  description: string | null;
  engine: string | null;
  access: SourceAccess | null;
  has_access: boolean;
  access_updated_at: string | null;
};

export type ObjectCategory =
  | "transaction_fact"
  | "master_data"
  | "dimension"
  | "reference"
  | "event";

export type BusinessDomainRef = {
  id: string;
  code: string;
  name: string;
};

export type ColumnSemantics = {
  semantic_type?: string | null;
  value_pattern?: string | null;
  unit?: string | null;
};

export type EnumCatalogEntry = {
  code: string;
  label: string;
  description?: string | null;
};

export type ObjectSemanticsPatch = {
  business_name?: string | null;
  business_description?: string | null;
  object_category?: ObjectCategory | null;
  grain_description?: string | null;
  business_primary_key?: string[] | null;
  business_domain_code?: string | null;
  evidence_summary?: string[] | null;
  open_questions?: string[] | null;
};

export type ColumnSemanticsPatch = {
  business_name?: string | null;
  business_description?: string | null;
  column_semantics?: ColumnSemantics | null;
  enum_catalog?: EnumCatalogEntry[] | null;
};

export type CatalogObject = {
  id: string;
  locator_key: string;
  source_id: string;
  object_type: string;
  schema_name: string;
  name: string;
  comment?: string | null;
  primary_key?: string[] | null;
  business_name: string | null;
  business_description: string | null;
  object_category?: ObjectCategory | string | null;
  grain_description?: string | null;
  business_primary_key?: string[] | null;
  business_domain?: BusinessDomainRef | null;
  evidence_summary?: string[] | null;
  open_questions?: string[] | null;
  semantic_source?: string | null;
  business_semantics_ready?: boolean;
  semantics_updated_at?: string | null;
  columns: CatalogColumn[];
  foreign_keys?: CatalogForeignKey[];
  indexes?: CatalogIndex[];
  ddl: string | null;
  is_present: boolean;
  collected_at: string | null;
};

export type CatalogColumn = {
  id: string;
  locator_key: string;
  name: string;
  data_type: string;
  nullable: boolean;
  default_value?: string | null;
  comment?: string | null;
  business_name: string | null;
  business_description: string | null;
  column_semantics?: ColumnSemantics | null;
  enum_catalog?: EnumCatalogEntry[] | null;
  semantic_source?: string | null;
  field_kind?: string;
  ordinal: number;
  is_present: boolean;
  normalized_type?: string | null;
};

export type CatalogForeignKey = {
  name: string;
  columns: string[];
  ref_schema: string;
  ref_table: string;
  ref_columns: string[];
  is_present: boolean;
};

export type CatalogIndex = {
  name: string;
  columns: string[];
  is_unique: boolean;
  is_present: boolean;
};

export type CatalogJoin = {
  id: string;
  from_column_id: string;
  to_column_id: string;
  from_column_locator_key?: string | null;
  to_column_locator_key?: string | null;
  evidence: string;
  join_kind?: string;
  join_expression?: string | null;
  created_by_user_id: string | null;
  created_at: string;
  is_rejected?: boolean;
  rejected_at?: string | null;
  rejected_by_user_id?: string | null;
};

export type JoinPathHop = {
  from_column_id: string;
  to_column_id: string;
  from_column_locator_key?: string | null;
  to_column_locator_key?: string | null;
  join_id: string;
  join_kind: string;
  join_expression?: string | null;
  evidence: string;
};

export type JoinPath = {
  target_object_id?: string | null;
  target_column_id?: string | null;
  hops: JoinPathHop[];
  path_summary: string;
};

export type JoinPathResult = {
  paths_found: number;
  paths: JoinPath[];
  direct_joins: CatalogJoin[];
  reason?: string | null;
};

export type QueryResult = {
  columns: string[];
  rows: unknown[][];
  truncated: boolean;
  duration_ms: number;
};

export type SampleResult = {
  columns: string[];
  rows: unknown[][];
  truncated: boolean;
  duration_ms: number;
  offset: number;
  limit: number;
  has_more: boolean;
  sql?: string | null;
};

export type SampleFilterOp = "eq" | "neq" | "contains" | "is_null";

export type SampleRequestBody = {
  columns?: string[] | null;
  filters?: Array<{
    column: string | null;
    op: SampleFilterOp;
    value?: string;
  }>;
  order_by?: Array<{ column: string; direction: "asc" | "desc" }>;
  offset?: number;
  limit?: number;
  include_sql?: boolean;
};

export type ColumnSemanticsBatchItem = {
  column_name: string;
  business_name?: string | null;
  business_description?: string | null;
  column_semantics?: ColumnSemantics | null;
  enum_catalog?: EnumCatalogEntry[] | null;
};

export type StructureDiffChange = {
  change: string;
  locator_key: string;
  [key: string]: unknown;
};

export type StructureDiff = {
  id: string;
  source_id: string;
  job_id: string;
  class: string;
  counts: Record<string, number>;
  created_at: string;
  changes?: StructureDiffChange[];
};

