export function decimalBytes(value: number | null) {
  if (value == null) return "—";
  const units = ["B", "kB", "MB", "GB", "TB", "PB"];
  let size = value, unit = 0;
  while (Math.abs(size) >= 1000 && unit < units.length - 1) { size /= 1000; unit++; }
  return `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(size)} ${units[unit]}`;
}

export function fleetPercent(value: number | null) {
  return value == null ? "—" : `${new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 }).format(value)}%`;
}

export function utcSample(value: string | null) {
  if (!value) return "—";
  const time = new Date(value);
  return Number.isFinite(time.valueOf()) ? time.toISOString().replace("T", " ").replace(/\.\d{3}Z$/, " UTC") : value;
}
