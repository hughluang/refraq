import type { ConnectorSpec, JsonSchemaProperty, SourceAccess } from "./types";

type Translate = (key: string, options?: Record<string, unknown>) => string;

export function propertyType(property: JsonSchemaProperty): string {
  return Array.isArray(property.type) ? property.type[0] : property.type ?? "string";
}

export function defaultsFromSchema(schema: ConnectorSpec): SourceAccess {
  return Object.fromEntries(Object.entries(schema.properties ?? {}).map(([key, prop]) => {
    const empty = propertyType(prop) === "object" ? {} : prop.enum?.[0] ?? "";
    return [key, prop.default ?? empty];
  }));
}

function scalarError(value: unknown, prop: JsonSchemaProperty, t: Translate) {
  const type = propertyType(prop);
  if (type === "integer" || type === "number") {
    if (typeof value !== "number" || !Number.isFinite(value) || (type === "integer" && !Number.isInteger(value))) {
      return t("sources.connection.invalidNumber");
    }
    if (prop.minimum != null && value < prop.minimum) return t("sources.connection.minimum", { limit: prop.minimum });
    if (prop.maximum != null && value > prop.maximum) return t("sources.connection.maximum", { limit: prop.maximum });
    return null;
  }
  if (typeof value !== "string") return t("sources.connection.invalidText");
  if (prop.enum && !prop.enum.includes(value)) return t("sources.connection.invalidOption");
  const length = Array.from(value).length;
  if (prop.minLength != null && length < prop.minLength) return t("sources.connection.minLength", { limit: prop.minLength });
  if (prop.maxLength != null && length > prop.maxLength) return t("sources.connection.maxLength", { limit: prop.maxLength });
  return null;
}

export function validateSourceAccess(schema: ConnectorSpec, access: SourceAccess, t: Translate): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const [key, prop] of Object.entries(schema.properties ?? {})) {
    const value = access[key];
    const path = `access.${key}`;
    if (schema.required?.includes(key) && (value == null || value === "")) {
      errors[path] = t("sources.validation.required");
    } else if (value !== undefined) {
      if (propertyType(prop) === "object") {
        if (!value || typeof value !== "object" || Array.isArray(value)) {
          errors[path] = t("sources.connection.invalidOptions");
          continue;
        }
        for (const [name, item] of Object.entries(value)) {
          const rule = prop.additionalProperties;
          if (rule === false) errors[path] = t("sources.connection.invalidOptions");
          const error = (prop.propertyNames && scalarError(name, prop.propertyNames, t))
            || (typeof rule === "object" && scalarError(item, rule, t));
          if (error) errors[`${path}.${name}`] = error;
        }
      } else {
        const error = scalarError(value, prop, t);
        if (error) errors[path] = error;
      }
    }
  }
  return errors;
}
