export type Tag = {
  id: string;
  name: string;
  description: string | null;
  entity_count: number;
  channel_count: number;
  created_at: string;
  updated_at: string;
};

export type TagSummary = {
  id: string;
  name: string;
  description: string | null;
  created_at: string;
  updated_at: string;
};

export type TagCreateBody = {
  name: string;
  description?: string | null;
};

export type TagPatchBody = {
  name?: string;
  description?: string | null;
};

export type TagFormValues = {
  name: string;
  description: string;
};
