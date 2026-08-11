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
