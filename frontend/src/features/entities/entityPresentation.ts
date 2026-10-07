import type {
  AttributeConfig,
  AttributeDraft,
  EntityAttribute,
  EntityVersion,
} from "@/features/entities/types";

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
  if (item.type === "dictionary") {
    return { dictionary_id: item.dictionary_id.trim() };
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
      business_key: item.business_key,
      description: item.description ?? "",
      max_length: config.max_length != null ? String(config.max_length) : "",
      precision: config.precision != null ? String(config.precision) : "",
      scale: config.scale != null ? String(config.scale) : "",
      dictionary_id: config.dictionary_id ?? "",
      dictionary_name: item.dictionary?.name ?? "",
      dictionary_display_name: item.dictionary?.display_name ?? "",
      dictionary_deprecated: item.dictionary?.deprecated ?? false,
      behind: item.behind ?? false,
      target_entity_id: config.target_entity_id ?? "",
      target_name: item.target?.name ?? "",
      target_table_name: item.target?.table_name ?? "",
      reference_key_type:
        item.reference_snapshot?.type === "string" ||
        item.reference_snapshot?.type === "integer"
          ? item.reference_snapshot.type
          : "",
      reference_max_length:
        item.reference_snapshot?.max_length != null
          ? String(item.reference_snapshot.max_length)
          : "",
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
    business_key: item.business_key,
    description: item.description.trim() || null,
    config: configFromDraft(item),
  }));
}

export const REFERENCE_SELF = "self";

const TABLE_NAME_MAX_LEN = 63;
const TABLE_NAME_RE = /^[a-z][a-z0-9_]*$/;
const PHYSICAL_TABLE_RE = /^.+__v[0-9]+__[0-9a-f]{16}$/;

export function isLegalTableName(value: string): boolean {
  const cleaned = value.trim();
  return (
    cleaned.length > 0 &&
    cleaned.length <= TABLE_NAME_MAX_LEN &&
    TABLE_NAME_RE.test(cleaned) &&
    !PHYSICAL_TABLE_RE.test(cleaned)
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

/** Label for a stored User id on a display surface. A missing User stays the id. */
export function userAttributeLabel(input: {
  userId: string;
  account?: string | null;
  displayName?: string | null;
}): string {
  const account = input.account?.trim() ?? "";
  const displayName = input.displayName?.trim() ?? "";
  if (displayName && account && displayName !== account) {
    return `${displayName} (${account})`;
  }
  return displayName || account || input.userId;
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
