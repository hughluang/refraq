export type JsonSchemaProperty = {
  type?: string | string[];
  description?: string;
  default?: unknown;
  enum?: string[];
  minimum?: number;
  maximum?: number;
  minLength?: number;
  maxLength?: number;
  pattern?: string;
  "x-secret"?: boolean;
  additionalProperties?: JsonSchemaProperty | boolean;
  properties?: Record<string, JsonSchemaProperty>;
  propertyNames?: JsonSchemaProperty;
};
