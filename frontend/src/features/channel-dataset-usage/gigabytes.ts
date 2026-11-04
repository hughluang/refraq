const BYTES_PER_GB = 1024 ** 3;

/** Used bytes and the remainder: one decimal, half away from zero, no trailing `.0`. */
export function formatDatasetGigabytes(bytes: number): string {
  const scaled = bytes / BYTES_PER_GB;
  const tenths = Math.sign(scaled) * Math.round(Math.abs(scaled) * 10);
  const whole = Math.trunc(tenths / 10);
  const fraction = Math.abs(tenths % 10);
  if (fraction === 0) return String(whole);
  return `${whole}.${fraction}`;
}

/** Ceiling text is the parameter integer, not the one-decimal rule. */
export function formatCeilingGigabytes(bytes: number): string {
  return String(Math.trunc(bytes / BYTES_PER_GB));
}
