export type HostMetricUnit = "number" | "bytes" | "byte-change" | "share" | "cpu-rate" | "cpu-step";

export function formatHostMetric(
  value: number | null,
  unit: HostMetricUnit,
  locale: string,
): string {
  if (value === null) return "—";
  switch (unit) {
    case "bytes":
      return formatHostBytes(value, locale);
    case "byte-change":
      return formatHostBytes(value, locale, true);
    case "share":
      return new Intl.NumberFormat(locale, {
        style: "percent",
        maximumFractionDigits: 2,
        ...(value !== 0 && Math.abs(value) < 0.0001
          ? { maximumSignificantDigits: 3 }
          : {}),
      }).format(value);
    case "cpu-rate":
      return `${formatHostNumber(value, locale)} CPU-s/s`;
    case "cpu-step":
      return `${formatHostNumber(value, locale)} CPU-s/step`;
    case "number":
      return formatHostNumber(value, locale);
  }
}

export function formatHostNumber(value: number | null, locale: string): string {
  if (value === null) return "—";
  return new Intl.NumberFormat(locale, {
    maximumFractionDigits: 2,
    ...(value !== 0 && Math.abs(value) < 0.01
      ? { maximumSignificantDigits: 3 }
      : {}),
  }).format(value);
}

export function formatHostBytes(
  value: number | null,
  locale: string,
  signed = false,
): string {
  if (value === null) return "—";
  const units = ["B", "KiB", "MiB", "GiB", "TiB"];
  let scaled = value;
  let unit = 0;
  while (Math.abs(scaled) >= 1024 && unit < units.length - 1) {
    scaled /= 1024;
    unit += 1;
  }
  const prefix = signed && value > 0 ? "+" : "";
  return `${prefix}${formatHostNumber(scaled, locale)} ${units[unit]}`;
}
