import type {
  ColumnDeclaration,
  SampleFilterOp,
  SampleRequestBody,
} from "@/features/sources/types";

export type { SampleFilterOp };

export type SampleFilter = {
  column: string | null;
  op: SampleFilterOp;
  value: string;
};

export type SampleFilterDraft = SampleFilter & {
  id: string;
};

export type SampleOrderBy = {
  column: string;
  direction: "asc" | "desc";
};

export type SampleAppliedParams = {
  limit: number;
  offset: number;
  filterKey: string;
  orderColumn: string | null;
  orderDirection: "asc" | "desc";
  columnsKey?: string;
  includeSql?: boolean;
};

export type BinaryCellPayload = {
  encoding: "base64";
  data: string;
};

export function isSampleFilterOp(value: string): value is SampleFilterOp {
  return (
    value === "eq" ||
    value === "neq" ||
    value === "contains" ||
    value === "is_null"
  );
}

function normalizeFilter(filter: SampleFilter) {
  return {
    column: filter.column,
    op: filter.op,
    value: filter.op === "is_null" ? "" : filter.value,
  };
}

export function sampleFilterSnapshot(
  filter: SampleFilter | readonly SampleFilter[],
): string {
  if (Array.isArray(filter)) {
    return JSON.stringify(
      filter.filter((item) => item.column != null).map(normalizeFilter),
    );
  }
  return JSON.stringify(normalizeFilter(filter as SampleFilter));
}

export function defaultSampleOrderColumn(object: {
  primary_key?: string[] | null;
  columns: ReadonlyArray<{ name: string; is_present: boolean }>;
}): string | null {
  const present = object.columns.filter((c) => c.is_present).map((c) => c.name);
  const pk0 = object.primary_key?.[0];
  if (pk0 != null && present.includes(pk0)) return pk0;
  return present[0] ?? null;
}

export function formatSampleCell(cell: unknown): string {
  if (cell === null || cell === undefined) return "NULL";
  if (typeof cell === "object") return JSON.stringify(cell);
  return String(cell);
}

export function isBinaryCell(cell: unknown): cell is BinaryCellPayload {
  if (cell == null || typeof cell !== "object" || Array.isArray(cell)) {
    return false;
  }
  const record = cell as Record<string, unknown>;
  return record.encoding === "base64" && typeof record.data === "string";
}

export function binaryByteLength(base64: string): number {
  const clean = base64.replace(/\s+/g, "");
  if (clean.length === 0) return 0;
  const padding = clean.endsWith("==") ? 2 : clean.endsWith("=") ? 1 : 0;
  return Math.max(0, Math.floor((clean.length * 3) / 4) - padding);
}

function fractionalDigitCount(value: string): number {
  const match = /\.(\d+)/.exec(value);
  if (!match) return 0;
  return match[1].replace(/0+$/, "").length;
}

export function cellExceedsDeclaredPrecision(
  cell: unknown,
  declaration?: ColumnDeclaration,
): boolean {
  if (!declaration || declaration.precision == null) return false;
  if (typeof cell === "number") {
    return fractionalDigitCount(String(cell)) > declaration.precision;
  }
  if (typeof cell === "string" && declaration.temporal_kind != null) {
    return fractionalDigitCount(cell) > declaration.precision;
  }
  return false;
}

export function buildSampleFilters(
  rows: readonly SampleFilter[],
  declarations: readonly ColumnDeclaration[] = [],
): Array<{ column: string; op: SampleFilterOp; value: string }> | null {
  const filters: Array<{ column: string; op: SampleFilterOp; value: string }> =
    [];
  for (const row of rows) {
    if (row.column == null) continue;
    const value = row.op === "is_null" ? "" : row.value;
    const declaration = declarations.find((item) => item.name === row.column);
    if (
      row.op !== "is_null" &&
      declaration?.temporal_kind != null &&
      declaration.precision != null &&
      fractionalDigitCount(value) > declaration.precision
    ) {
      return null;
    }
    filters.push({
      column: row.column,
      op: row.op,
      value,
    });
  }
  return filters;
}

export function buildSampleRequest(
  filter: SampleFilter | readonly SampleFilter[],
  orderColumn: string | null,
  orderDirection: SampleOrderBy["direction"],
  offset: number,
  limit: number,
  declarations: readonly ColumnDeclaration[] = [],
  options?: {
    columns?: readonly string[] | null;
    includeSql?: boolean;
  },
): SampleRequestBody | null {
  const rows = Array.isArray(filter) ? filter : [filter as SampleFilter];
  const filters = buildSampleFilters(rows, declarations);
  if (filters == null) {
    return null;
  }
  const order_by: SampleOrderBy[] =
    orderColumn != null ? [{ column: orderColumn, direction: orderDirection }] : [];
  const body: SampleRequestBody = {
    filters,
    order_by,
    offset,
    limit,
    include_sql: options?.includeSql ?? false,
  };
  if (options?.columns && options.columns.length > 0) {
    body.columns = [...options.columns];
  }
  return body;
}

export function isSampleStale(
  applied: SampleAppliedParams | null,
  current: SampleAppliedParams,
): boolean {
  if (applied == null) return false;
  return (
    applied.limit !== current.limit ||
    applied.offset !== current.offset ||
    applied.filterKey !== current.filterKey ||
    applied.orderColumn !== current.orderColumn ||
    applied.orderDirection !== current.orderDirection ||
    (applied.columnsKey ?? "") !== (current.columnsKey ?? "") ||
    Boolean(applied.includeSql) !== Boolean(current.includeSql)
  );
}

export function isUnstableOrder(
  offset: number,
  orderColumn: string | null,
): boolean {
  return offset > 0 && !orderColumn;
}
