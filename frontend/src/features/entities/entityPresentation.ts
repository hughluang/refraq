import type {
  AttributeDraft,
  EntityAttribute,
  EntityVersion,
} from "@/features/entities/types";

export function draftsFromVersion(version: EntityVersion): AttributeDraft[] {
  return (version.attributes ?? []).map((item) => ({
    name: item.name,
    normalized_type: item.normalized_type,
    nullable: item.nullable,
    unique: item.unique,
    indexed: item.indexed,
    description: item.description ?? "",
  }));
}

export function attributesFromDrafts(
  attributes: AttributeDraft[],
): EntityAttribute[] {
  return attributes
    .filter((item) => item.name.trim() !== "")
    .map((item) => ({
      name: item.name.trim(),
      normalized_type: item.normalized_type,
      nullable: item.nullable,
      unique: item.unique,
      indexed: item.indexed,
      description: item.description.trim() || null,
    }));
}
