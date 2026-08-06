export type Source = {
  id: string;
  key: string;
  name: string;
  kind: string;
  status: string;
  description: string | null;
  database_name: string | null;
  schema_filter: string | null;
};

export type Connection = {
  id: string;
  source_id: string;
  name: string;
  engine: string;
  host: string;
  port: number;
  status: string;
  has_secret: boolean;
  secret_updated_at: string | null;
};

export type CatalogObject = {
  id: string;
  source_id: string;
  collected_from_connection_id: string | null;
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
