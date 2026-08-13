import type { StructureDiffChange } from "@/features/sources/types";

export const CHANGE_ORDER = [
  "object_removed",
  "column_removed",
  "type_changed",
  "pk_changed",
  "nullable_tightened",
  "object_added",
  "column_added",
  "nullable_widened",
  "comment_or_default_changed",
  "fk_added",
  "fk_removed",
  "index_added",
  "index_removed",
] as const;

export type ChangeGroup = {
  change: string;
  items: StructureDiffChange[];
};

export function groupChanges(
  changes: StructureDiffChange[] | undefined,
): ChangeGroup[] {
  const buckets = new Map<string, StructureDiffChange[]>();
  for (const item of changes ?? []) {
    const key = item.change || "unknown";
    const list = buckets.get(key);
    if (list) list.push(item);
    else buckets.set(key, [item]);
  }
  const known = CHANGE_ORDER.filter((key) => buckets.has(key)).map((key) => ({
    change: key,
    items: buckets.get(key) ?? [],
  }));
  const extras = [...buckets.keys()]
    .filter((key) => !(CHANGE_ORDER as readonly string[]).includes(key))
    .sort()
    .map((key) => ({ change: key, items: buckets.get(key) ?? [] }));
  return [...known, ...extras];
}

export const COUNT_ORDER = [
  "objects_added",
  "objects_removed",
  "columns_added",
  "columns_removed",
  "type_changed",
  "pk_changed",
  "nullable_tightened",
  "nullable_widened",
  "comments_or_defaults",
] as const;
