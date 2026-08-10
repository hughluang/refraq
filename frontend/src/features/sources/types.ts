export type Engine = "postgresql" | "mssql" | "oracle";

export type SourceAccess = Record<string, unknown>;

export type JsonSchemaProperty = {
  type?: string | string[];
  description?: string;
  default?: unknown;
  enum?: string[];
  minimum?: number;
  maximum?: number;
  minLength?: number;
  maxLength?: number;
  "x-secret"?: boolean;
  additionalProperties?: JsonSchemaProperty | boolean;
  properties?: Record<string, JsonSchemaProperty>;
  propertyNames?: JsonSchemaProperty;
};

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
  database_name: string | null;
  schema_filter: string | null;
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

export type TimeSemantics = {
  primary_time_field?: string | null;
  time_role?: string | null;
};

export type StatusSemantics = {
  primary_status_field?: string | null;
  status_meaning?: string | null;
};

export type RelationSummary = {
  input_role_hint?: string | null;
  main_upstream_or_dimension_objects?: string[] | null;
  likely_child_objects?: string[] | null;
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
  time_semantics?: TimeSemantics | null;
  status_semantics?: StatusSemantics | null;
  relation_summary?: RelationSummary | null;
  business_domain?: string | null;
  evidence_summary?: string[] | null;
  confidence?: number | null;
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
  time_semantics?: TimeSemantics | null;
  status_semantics?: StatusSemantics | null;
  relation_summary?: RelationSummary | null;
  business_domain?: string | null;
  evidence_summary?: string[] | null;
  confidence?: number | null;
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
  origin?: string;
  created_by_user_id: string | null;
  created_at: string;
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
  origin: string;
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

export type ColumnSemanticsBatchItem = {
  column_name: string;
  business_name?: string | null;
  business_description?: string | null;
  column_semantics?: ColumnSemantics | null;
  enum_catalog?: EnumCatalogEntry[] | null;
};

export type Job = {
  id: string;
  kind: string;
  status: string;
  input: Record<string, unknown>;
  created_by_user_id: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
  error_code: string | null;
  error_message: string | null;
};
