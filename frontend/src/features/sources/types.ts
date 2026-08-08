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

export type CatalogObject = {
  id: string;
  source_id: string;
  object_type: string;
  schema_name: string;
  name: string;
  business_name: string | null;
  business_description: string | null;
  columns: CatalogColumn[];
  ddl: string | null;
  is_present: boolean;
  collected_at: string | null;
};

export type CatalogColumn = {
  id: string;
  name: string;
  data_type: string;
  nullable: boolean;
  business_name: string | null;
  business_description: string | null;
  ordinal: number;
  is_present: boolean;
};

export type CatalogJoin = {
  id: string;
  from_column_id: string;
  to_column_id: string;
  evidence: string;
  created_by_user_id: string | null;
  created_at: string;
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
