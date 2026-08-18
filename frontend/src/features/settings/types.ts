import type { JsonSchemaProperty } from "@/lib/json-schema";

export type SettingsSource = "seed" | "user";

export type SettingsValue = number | string | boolean | null;

export type SystemParameter = {
  key: string;
  value: SettingsValue;
  seed: SettingsValue;
  source: SettingsSource;
  constraint: JsonSchemaProperty;
  group: string;
  operator_action_required: boolean;
  label_key: string;
  help_key: string;
  apply_note_key: string;
  updated_at: string | null;
  updated_by_user_id: string | null;
  updated_by_account: string | null;
};

export type PlatformSettings = {
  parameters: SystemParameter[];
};
