import type { ColumnDeclaration, SampleRequestBody } from "@/features/sources/types";

export type SampleFilterOp = "eq" | "neq" | "contains" | "is_null";

export type SampleFilter = {
  column: string | null;
  op: SampleFilterOp;
  value: string;
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
};

export function isSampleFilterOp(value: string): value is SampleFilterOp {
  return (
    value === "eq" ||
    value === "neq" ||
    value === "contains" ||
    value === "is_null"
  );
}

export function sampleFilterSnapshot(filter: SampleFilter): string {
  return JSON.stringify({
    column: filter.column,
    op: filter.op,
    value: filter.op === "is_null" ? "" : filter.value,
  });
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

function fractionalDigitCount(value: string): number {
  const match = /\.(\d+)/.exec(value);
  if (!match) return 0;
  return match[1].replace(/0+$/, "").length;
}

export function buildSampleRequest(
  filter: SampleFilter,
  orderColumn: string | null,
  orderDirection: SampleOrderBy["direction"],
  offset: number,
  limit: number,
  declarations: readonly ColumnDeclaration[] = [],
): SampleRequestBody | null {
  const value = filter.op === "is_null" ? "" : filter.value;
  const declaration =
    filter.column == null
      ? undefined
      : declarations.find((item) => item.name === filter.column);
  if (
    filter.op !== "is_null" &&
    declaration?.temporal_kind != null &&
    declaration.precision != null &&
    fractionalDigitCount(value) > declaration.precision
  ) {
    return null;
  }
  const filters =
    filter.column != null
      ? [
          {
            column: filter.column,
            op: filter.op,
            value,
          },
        ]
      : [];
  const order_by: SampleOrderBy[] =
    orderColumn != null ? [{ column: orderColumn, direction: orderDirection }] : [];
  return {
    filters,
    order_by,
    offset,
    limit,
    include_sql: false,
  };
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
    applied.orderDirection !== current.orderDirection
  );
}

export function isUnstableOrder(
  offset: number,
  orderColumn: string | null,
): boolean {
  return offset > 0 && !orderColumn;
}
