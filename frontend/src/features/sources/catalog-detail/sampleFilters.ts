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
