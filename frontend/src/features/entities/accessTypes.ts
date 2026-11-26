export type AccessSubject = {
  type: "user" | "role" | "group";
  id: string;
  display_name?: string | null;
  missing?: boolean;
};

export type AccessLevel = {
  key: string;
  mode: "clear" | { type: string; [key: string]: unknown };
};

export type CompatibleSubjectAttribute = {
  key: string;
  name: string;
  value_type: string;
  multi_value: boolean;
};

export type AccessLadder = {
  attribute_id: string;
  attribute_name: string;
  attribute_display_name?: string | null;
  type: string;
  value_type?: string;
  business_key?: boolean;
  codes?: string[];
  accepted_masks?: string[];
  operators?: string[];
  compatible_subject_attributes?: CompatibleSubjectAttribute[];
  levels: AccessLevel[];
};

export type AccessProfile = {
  id: string;
  entity_id: string;
  key: string;
  name: string;
  description: string | null;
  columns: {
    attribute_id: string;
    attribute_name?: string | null;
    attribute_display_name?: string | null;
    level: string;
  }[];
  broken: boolean;
  broken_reasons: string[];
};

export type GrantWarning = {
  path: string;
  attribute_id: string;
  message: string;
};

export type AccessGrant = {
  id: string;
  subject: AccessSubject;
  profile_id: string;
  row_rule: Record<string, unknown> | null;
  actions: string[];
  status: string;
  locked?: boolean;
  valid_until: string | null;
  broken: boolean;
  broken_reasons?: string[];
  warnings?: GrantWarning[];
};

export type AccessRestriction = {
  id: string;
  applies_to: { mode: "all" | "only" | "except" | string; subjects: AccessSubject[] };
  row_rule: Record<string, unknown> | null;
  deny_columns: string[];
  ceilings: { attribute_id: string; level: string }[];
  actions: string[];
  broken?: boolean;
  broken_reasons?: string[];
};

export type PreviewIdentity = {
  type: "user" | "role" | "group";
  id: string | null;
  display_name: string;
};

export type PreviewAccessResponse = {
  policy_revision: number;
  identities?: PreviewIdentity[];
  effective_grants: string[];
  schema: DataSchema;
  rows: {
    items: Record<string, unknown>[];
    total: number;
    limit?: number;
    offset?: number;
  } | null;
};

export type AccessSummary = {
  entity_id: string;
  head_version_id: string | null;
  policy_revision: number;
  views: {
    state: "ready" | "pending" | "failed";
    revision: number;
    single_profile_views: number;
    combinations: number;
    combination_limit: number;
    subjects_over_limit: number;
    latest_job_id: string | null;
  };
  ladders: AccessLadder[];
  profiles: AccessProfile[];
  grants: AccessGrant[];
  restrictions: AccessRestriction[];
};

export type DataSort = { field: string; direction: "asc" | "desc" };

export type DataAttribute = {
  name: string;
  display_name?: string | null;
  type: string;
  attribute_id?: string;
  description?: string | null;
  config?: Record<string, unknown>;
  codes?: { code: string; label: string | null; writable: boolean }[];
  operators?: string[];
  upsert_key?: boolean;
  writable?: boolean;
  presentation?: {
    row_varying: boolean;
    may_be_withheld: boolean;
    levels: { key: string; mode: unknown }[];
  };
  target?: { entity_id: string; table_name: string; business_key: string | null } | null;
};

export type DataSchema = {
  entity: { table_name: string; writable: boolean; name: string };
  head?: { version_id: string; version: number };
  row_id?: { type: string; operators: string[] };
  limits?: {
    page_limit_default: number;
    page_limit_max: number;
    filter_leaves_max: number;
    filter_depth_max: number;
    filter_in_values_max: number;
  };
  attributes: DataAttribute[];
  withheld_field: string | null;
  access?: { policy_revision: number; narrowed: boolean };
  business_key: string | null;
};
