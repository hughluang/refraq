import type { Instant } from "@/lib/instant";

export type TypeMappingOrigin = "product" | "job" | "user";

export type PatchableNormalizedType =
  | "string"
  | "integer"
  | "number"
  | "decimal"
  | "boolean"
  | "date"
  | "timestamp"
  | "time"
  | "interval"
  | "binary"
  | "json"
  | "array";

export type TypeMapping = {
  id: string;
  engine: string;
  native_type: string;
  normalized_type: string;
  origin: TypeMappingOrigin;
  created_at: Instant;
  updated_at: Instant;
};
