import type {
  AttributeConfig,
  AttributeDraft,
  EntityAttribute,
  EntityVersion,
  EnumerationEntry,
} from "@/features/entities/types";

function enumerationToText(
  entries: EnumerationEntry[] | null | undefined,
): string {
  if (!entries || entries.length === 0) return "";
  return entries
    .map((entry) =>
      entry.label == null ? entry.code : `${entry.code}|${entry.label}`,
    )
    .join("\n");
}

export function enumerationEntriesFromText(
  text: string,
): EnumerationEntry[] | null {
  const lines = text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line !== "");
  if (lines.length === 0) return null;
  return lines.map((line) => {
    const sep = line.indexOf("|");
    if (sep < 0) return { code: line };
    return { code: line.slice(0, sep), label: line.slice(sep + 1) };
  });
}

function parsedInt(value: string): number | undefined {
  if (value.trim() === "") return undefined;
  const parsed = Number.parseInt(value, 10);
  return Number.isNaN(parsed) ? undefined : parsed;
}

function configFromDraft(item: AttributeDraft): AttributeConfig {
  if (item.type === "string") {
    const maxLength = parsedInt(item.max_length);
    return maxLength == null ? {} : { max_length: maxLength };
  }
  if (item.type === "decimal") {
    const precision = parsedInt(item.precision);
    const scale = parsedInt(item.scale);
    return {
      ...(precision == null ? {} : { precision }),
      ...(scale == null ? {} : { scale }),
    };
  }
  if (item.type === "enumeration") {
    return { entries: enumerationEntriesFromText(item.enumeration_text) ?? [] };
  }
  if (item.type === "reference") {
    return { target_entity_id: item.target_entity_id.trim() };
  }
  return {};
}

export function draftsFromVersion(version: EntityVersion): AttributeDraft[] {
  return (version.attributes ?? []).map((item) => {
    const config = item.config ?? {};
    return {
      type: item.type,
      name: item.name,
      required: item.required,
      unique: item.unique,
      indexed: item.indexed,
      description: item.description ?? "",
      max_length: config.max_length != null ? String(config.max_length) : "",
      precision: config.precision != null ? String(config.precision) : "",
      scale: config.scale != null ? String(config.scale) : "",
      enumeration_text: enumerationToText(config.entries),
      target_entity_id: config.target_entity_id ?? "",
      target_name: item.target?.name ?? "",
      target_table_name: item.target?.table_name ?? "",
    };
  });
}

export function attributesFromDrafts(
  attributes: AttributeDraft[],
): EntityAttribute[] {
  return attributes.map((item) => ({
    type: item.type,
    name: item.name.trim(),
    required: item.required,
    unique: item.unique,
    indexed: item.indexed,
    description: item.description.trim() || null,
    config: configFromDraft(item),
  }));
}

export const REFERENCE_SELF = "self";

const TABLE_NAME_MAX_LEN = 48;
const TABLE_NAME_RE = /^[a-z][a-z0-9_]*$/;
const ARCHIVE_TABLE_RE = /__rfq_v[0-9]+$/;

export function isLegalTableName(value: string): boolean {
  const cleaned = value.trim();
  return (
    cleaned.length > 0 &&
    cleaned.length <= TABLE_NAME_MAX_LEN &&
    TABLE_NAME_RE.test(cleaned) &&
    !ARCHIVE_TABLE_RE.test(cleaned)
  );
}

export function referenceOptionLabel(input: {
  name: string;
  tableName: string;
  emptyNameLabel: string;
}): string {
  const name = input.name.trim();
  const tableName = input.tableName.trim();
  const title = name || input.emptyNameLabel;
  if (!isLegalTableName(tableName)) return title;
  return `${title}（${tableName}）`;
}

export function referenceSummaryLabel(input: {
  targetEntityId: string;
  selfEntityId: string | null;
  selfName: string;
  selfTableName: string;
  cachedName: string;
  cachedTableName: string;
  emptyNameLabel: string;
}): string | null {
  const id = input.targetEntityId.trim();
  if (!id) return null;
  const isSelf =
    id === REFERENCE_SELF ||
    (input.selfEntityId != null && id === input.selfEntityId);
  if (isSelf) {
    return referenceOptionLabel({
      name: input.selfName,
      tableName: input.selfTableName,
      emptyNameLabel: input.emptyNameLabel,
    });
  }
  if (input.cachedName.trim() || isLegalTableName(input.cachedTableName)) {
    return referenceOptionLabel({
      name: input.cachedName,
      tableName: input.cachedTableName,
      emptyNameLabel: input.cachedTableName.trim() || id,
    });
  }
  return id;
}
