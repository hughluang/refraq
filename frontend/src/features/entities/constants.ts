import type { NormalizedType } from "@/features/entities/types";

export const NORMALIZED_TYPES: NormalizedType[] = [
  "string",
  "integer",
  "number",
  "boolean",
  "date",
  "timestamp",
  "time",
  "interval",
  "binary",
  "json",
  "array",
  "unknown",
];

export const EMPTY_ATTRIBUTE: {
  name: string;
  normalized_type: NormalizedType;
  nullable: boolean;
  unique: boolean;
  indexed: boolean;
  description: string;
} = {
  name: "",
  normalized_type: "string",
  nullable: false,
  unique: false,
  indexed: false,
  description: "",
};

export const DROP_TABLE_PERMISSION = "entity:drop_table";
