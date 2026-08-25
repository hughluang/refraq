import type {
  CatalogColumn,
  CatalogForeignKey,
  ColumnSemantics,
  ColumnSemanticsBatchItem,
  EnumCatalogEntry,
} from "@/features/sources/types";

export type ColumnDraft = {
  business_name: string;
  business_description: string;
  column_semantics: ColumnSemantics;
  enum_catalog: EnumCatalogEntry[];
};

export type ColumnFilter =
  | "all"
  | "empty"
  | "filled"
  | "enum"
  | "pk"
  | "fk"
  | "absent";

export function draftFromColumn(col: CatalogColumn): ColumnDraft {
  return {
    business_name: col.business_name ?? "",
    business_description: col.business_description ?? "",
    column_semantics: {
      semantic_type: col.column_semantics?.semantic_type ?? "",
      value_pattern: col.column_semantics?.value_pattern ?? "",
      unit: col.column_semantics?.unit ?? "",
    },
    enum_catalog: (col.enum_catalog ?? []).map((e) => ({
      code: e.code,
      label: e.label,
      description: e.description ?? "",
    })),
  };
}

export function draftsFromColumns(
  columns: ReadonlyArray<CatalogColumn>,
): Record<string, ColumnDraft> {
  const next: Record<string, ColumnDraft> = {};
  for (const col of columns) {
    next[col.id] = draftFromColumn(col);
  }
  return next;
}

export function draftsEqual(a: ColumnDraft, b: ColumnDraft): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

export function normalizeForSave(draft: ColumnDraft) {
  const semanticType = draft.column_semantics.semantic_type?.trim() || null;
  const valuePattern = draft.column_semantics.value_pattern?.trim() || null;
  const unit = draft.column_semantics.unit?.trim() || null;
  const hasSemantics = Boolean(semanticType || valuePattern || unit);
  return {
    business_name: draft.business_name,
    business_description: draft.business_description,
    column_semantics: hasSemantics
      ? {
          semantic_type: semanticType,
          value_pattern: valuePattern,
          unit,
        }
      : null,
    enum_catalog: draft.enum_catalog
      .filter((e) => e.code.trim())
      .map((e) => ({
        code: e.code.trim(),
        label: e.label.trim() || e.code.trim(),
        description: e.description?.trim() || null,
      })),
  };
}

export function primaryKeyNames(
  primaryKey: ReadonlyArray<string> | null | undefined,
): Set<string> {
  return new Set(primaryKey ?? []);
}

export function foreignKeyNames(
  foreignKeys: ReadonlyArray<Pick<CatalogForeignKey, "columns">> | null | undefined,
): Set<string> {
  const set = new Set<string>();
  for (const fk of foreignKeys ?? []) {
    for (const name of fk.columns) set.add(name);
  }
  return set;
}

export function dirtyColumnIds(
  columns: ReadonlyArray<CatalogColumn>,
  drafts: Record<string, ColumnDraft>,
  baseline: Record<string, ColumnDraft>,
): string[] {
  return columns
    .filter((col) => {
      const draft = drafts[col.id];
      const base = baseline[col.id];
      if (!draft || !base) return false;
      return !draftsEqual(draft, base);
    })
    .map((c) => c.id);
}

export function batchItemsFromDirty(
  columns: ReadonlyArray<CatalogColumn>,
  drafts: Record<string, ColumnDraft>,
  dirtyIds: ReadonlyArray<string>,
): ColumnSemanticsBatchItem[] {
  return dirtyIds.map((id) => {
    const col = columns.find((c) => c.id === id);
    const draft = drafts[id];
    if (!col || !draft) {
      throw new Error(`dirty column missing: ${id}`);
    }
    return {
      column_name: col.name,
      ...normalizeForSave(draft),
    };
  });
}

/**
 * Filter columns by query and facet. `drafts` should be the saved baseline
 * (not the live edit buffer) so typing into a row does not remove it mid-edit.
 */
export function filterColumns(
  columns: ReadonlyArray<CatalogColumn>,
  drafts: Record<string, ColumnDraft>,
  opts: {
    query: string;
    filter: ColumnFilter;
    pkNames: Set<string>;
    fkNames: Set<string>;
  },
): CatalogColumn[] {
  const query = opts.query.trim().toLowerCase();
  return columns.filter((col) => {
    const draft = drafts[col.id] ?? draftFromColumn(col);
    if (query) {
      const hay =
        `${col.name} ${draft.business_name} ${col.locator_key}`.toLowerCase();
      if (!hay.includes(query)) return false;
    }
    const hasName = Boolean(draft.business_name.trim());
    const hasDesc = Boolean(draft.business_description.trim());
    const hasEnum = draft.enum_catalog.length > 0;
    switch (opts.filter) {
      case "empty":
        return !(hasName && hasDesc);
      case "filled":
        return hasName && hasDesc;
      case "enum":
        return hasEnum;
      case "pk":
        return opts.pkNames.has(col.name);
      case "fk":
        return opts.fkNames.has(col.name);
      case "absent":
        return !col.is_present;
      default:
        return true;
    }
  });
}

/** Full draft reset only when the Catalog Object identity or chrome Refresh epoch changes. */
export function shouldReplaceColumnDrafts(input: {
  objectId: string;
  previousObjectId: string | undefined;
  reloadEpoch: number;
  previousReloadEpoch: number | undefined;
}): boolean {
  if (
    input.previousObjectId === undefined ||
    input.previousReloadEpoch === undefined
  ) {
    return true;
  }
  return (
    input.objectId !== input.previousObjectId ||
    input.reloadEpoch !== input.previousReloadEpoch
  );
}

