export type DictionaryEntry = {
  code: string;
  label?: string | null;
  active: boolean;
};

export type DictionaryUsage = {
  entity_id: string;
  entity_name: string;
  table_name: string;
  attribute_name: string;
  version_id: string;
  version: number;
  publish_status: string;
  behind: boolean;
};

export type Dictionary = {
  id: string;
  name: string;
  display_name: string;
  description: string | null;
  revision: number;
  deprecated_at: string | null;
  entry_count: number;
  entries?: DictionaryEntry[];
  usages?: DictionaryUsage[];
  created_at: string;
  updated_at: string;
};

export type DictionaryEntryDraft = {
  code: string;
  label: string;
  active: boolean;
};

export type DictionaryFormValues = {
  name: string;
  display_name: string;
  description: string;
  entries: DictionaryEntryDraft[];
};

export type DictionaryCreateBody = {
  name: string;
  display_name: string;
  description?: string | null;
  entries: DictionaryEntry[];
};

export type DictionaryPatchBody = {
  display_name?: string;
  description?: string | null;
  deprecated?: boolean;
  entries?: DictionaryEntry[];
};
