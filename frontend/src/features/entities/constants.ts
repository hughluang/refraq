import type { AttributeType } from "@/features/entities/types";

export const EMPTY_ATTRIBUTE: {
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
  reference_key_type: "" | "string" | "integer";
  reference_max_length: string;
} = {
  type: "string",
  name: "",
  required: false,
  unique: false,
  indexed: false,
  business_key: false,
  description: "",
  max_length: "",
  precision: "",
  scale: "",
  dictionary_id: "",
  dictionary_name: "",
  dictionary_display_name: "",
  dictionary_deprecated: false,
  behind: false,
  target_entity_id: "",
  target_name: "",
  target_table_name: "",
  reference_key_type: "",
  reference_max_length: "",
};

export const DROP_TABLE_PERMISSION = "entity:drop_table";
