export type SubjectValueType =
  | "string"
  | "integer"
  | "date"
  | "dictionary"
  | "user";

export type UserGroup = {
  id: string;
  key: string;
  name: string;
  description: string | null;
  member_count: number;
  created_at: string;
  updated_at: string;
};

export type SubjectAttribute = {
  id: string;
  key: string;
  name: string;
  description: string | null;
  value_type: SubjectValueType;
  dictionary_id: string | null;
  multi_value: boolean;
  created_at: string;
  updated_at: string;
};

export type SubjectValues = Record<string, Array<string | number>>;

export type UserSubjectValues = {
  values: SubjectValues;
  effective: SubjectValues;
};
