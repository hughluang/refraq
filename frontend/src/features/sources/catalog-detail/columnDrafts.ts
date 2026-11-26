import type {
  CatalogColumn,
  CatalogForeignKey,
  CatalogIndex,
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
  | "dirty"
  | "enum"
  | "pk"
  | "fk"
  | "indexed"
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

export function foreignKeyMap(
  foreignKeys: ReadonlyArray<CatalogForeignKey> | null | undefined,
): Map<string, CatalogForeignKey[]> {
  const map = new Map<string, CatalogForeignKey[]>();
  for (const fk of foreignKeys ?? []) {
    for (const name of fk.columns) {
      const list = map.get(name);
      if (list) {
        list.push(fk);
      } else {
        map.set(name, [fk]);
      }
    }
  }
  return map;
}

export function uniqueKeyNames(
  indexes: ReadonlyArray<CatalogIndex> | null | undefined,
): Set<string> {
  const set = new Set<string>();
  for (const idx of indexes ?? []) {
    if (!idx.is_unique) continue;
    for (const name of idx.columns) set.add(name);
  }
  return set;
}

export function indexedNames(
  indexes: ReadonlyArray<CatalogIndex> | null | undefined,
): Set<string> {
  const set = new Set<string>();
  for (const idx of indexes ?? []) {
    for (const name of idx.columns) set.add(name);
  }
  return set;
}

export function distinctNormalizedTypes(
  columns: ReadonlyArray<CatalogColumn>,
): string[] {
  const set = new Set<string>();
  for (const col of columns) {
    const nt = col.normalized_type?.trim();
    if (nt) set.add(nt);
  }
  return Array.from(set).sort((a, b) => a.localeCompare(b));
}

export function hasUnknownNormalizedType(
  columns: ReadonlyArray<CatalogColumn>,
): boolean {
  return columns.some((col) => col.normalized_type === "unknown");
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
 * Parse pasted enum text (TSV, `code: label`, CSV, or single code per line).
 */
export function parseBulkEnumText(raw: string): EnumCatalogEntry[] {
  const entries: EnumCatalogEntry[] = [];
  for (const rawLine of raw.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line) continue;
    let code = "";
    let label = "";
    let description = "";
    if (line.includes("\t")) {
      const parts = line.split("\t");
      code = (parts[0] ?? "").trim();
      label = (parts[1] ?? "").trim() || code;
      description = parts.slice(2).join(" ").trim();
    } else if (line.includes(":")) {
      const idx = line.indexOf(":");
      code = line.slice(0, idx).trim();
      label = line.slice(idx + 1).trim() || code;
    } else if (line.includes(",")) {
      const parts = line.split(",");
      code = (parts[0] ?? "").trim();
      label = (parts[1] ?? "").trim() || code;
      description = parts.slice(2).join(",").trim();
    } else {
      code = line;
      label = line;
    }
    if (!code) continue;
    entries.push({ code, label, description });
  }
  return entries;
}

/**
 * Filter columns by query and facet. `baseline` is used for semantics completeness
 * checks so typing into a row does not remove it mid-edit, while `drafts` is
 * included in search matching and dirty checks.
 */
export function filterColumns(
  columns: ReadonlyArray<CatalogColumn>,
  drafts: Record<string, ColumnDraft>,
  opts: {
    query: string;
    filter: ColumnFilter;
    normalizedType?: string;
    pkNames: Set<string>;
    fkNames: Set<string>;
    indexedNames?: Set<string>;
    dirtyIds?: Set<string>;
    baseline?: Record<string, ColumnDraft>;
  },
): CatalogColumn[] {
  const query = opts.query.trim().toLowerCase();
  const statusMap = opts.baseline ?? drafts;
  return columns.filter((col) => {
    const draft = drafts[col.id] ?? draftFromColumn(col);
    const statusDraft = statusMap[col.id] ?? draft;
    if (query) {
      const hay = [
        col.name,
        col.business_name ?? "",
        col.business_description ?? "",
        col.comment ?? "",
        col.data_type,
        col.normalized_type ?? "",
        col.column_semantics?.semantic_type ?? "",
        col.locator_key,
        draft.business_name,
        draft.business_description,
        draft.column_semantics.semantic_type ?? "",
      ]
        .join(" ")
        .toLowerCase();
      if (!hay.includes(query)) return false;
    }
    if (opts.normalizedType && opts.normalizedType !== "all") {
      if ((col.normalized_type ?? "") !== opts.normalizedType) return false;
    }
    const hasName = Boolean(statusDraft.business_name.trim());
    const hasDesc = Boolean(statusDraft.business_description.trim());
    const hasEnum = draft.enum_catalog.length > 0;
    switch (opts.filter) {
      case "empty":
        return !(hasName && hasDesc);
      case "filled":
        return hasName && hasDesc;
      case "dirty":
        return opts.dirtyIds ? opts.dirtyIds.has(col.id) : false;
      case "enum":
        return hasEnum;
      case "pk":
        return opts.pkNames.has(col.name);
      case "fk":
        return opts.fkNames.has(col.name);
      case "indexed":
        return opts.indexedNames?.has(col.name) ?? false;
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
