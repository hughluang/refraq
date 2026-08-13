export type TypeMappingOrigin = "product" | "job" | "user";

export type PatchableNormalizedType =
  | "string"
  | "integer"
  | "number"
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
  created_at: string;
  updated_at: string;
};
