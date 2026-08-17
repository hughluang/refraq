/** Map API Running Time Limit onto the NumberInput value. Null/absent → empty. */
export function timeoutFromTask(value: number | null | undefined): number | "" {
  return value != null ? value : "";
}

/** Map empty NumberInput to API null (no control). Does not coerce invalid numbers. */
export function timeoutPayload(value: number | ""): number | null {
  return value === "" ? null : value;
}

/** Empty (no control) or a positive integer second count. */
export function isAllowedTimeoutInput(value: number | ""): boolean {
  return value === "" || (typeof value === "number" && Number.isInteger(value) && value >= 1);
}
