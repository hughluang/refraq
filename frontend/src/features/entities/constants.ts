import type { AttributeType } from "@/features/entities/types";

export const EMPTY_ATTRIBUTE: {
  type: AttributeType;
  name: string;
  required: boolean;
  unique: boolean;
  indexed: boolean;
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
} = {
  type: "string",
  name: "",
  required: false,
  unique: false,
  indexed: false,
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
};

export const DROP_TABLE_PERMISSION = "entity:drop_table";
