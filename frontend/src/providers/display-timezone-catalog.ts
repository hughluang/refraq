/** Sentinel Select value for “follow browser” → API null. */
export const FOLLOW_BROWSER_TIMEZONE = "";

/** Canonical IANA ids from the runtime (ICU / tzdata). */
export function listIanaTimeZones(): string[] {
  const supported =
    typeof Intl !== "undefined" &&
    "supportedValuesOf" in Intl &&
    typeof Intl.supportedValuesOf === "function"
      ? Intl.supportedValuesOf("timeZone")
      : [];
  const zones = new Set(supported);
  zones.add("UTC");
  return Array.from(zones).sort((a, b) => a.localeCompare(b));
}
