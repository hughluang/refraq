import type { TokenMetadata, TokenStatus } from "@/features/tokens/types";

export function tokenStatus(
  token: TokenMetadata,
  now: Date = new Date(),
): TokenStatus {
  if (token.revoked_at) {
    return "revoked";
  }
  if (new Date(token.expires_at).getTime() <= now.getTime()) {
    return "expired";
  }
  return "active";
}

export function formatTokenInstant(value: string | null): string {
  if (!value) {
    return "—";
  }
  return new Date(value).toLocaleString();
}

/** Value for `<input type="datetime-local">` in the browser's local zone. */
export function toDatetimeLocalValue(date: Date): string {
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** Convert datetime-local string to ISO-8601 for the API. */
export function datetimeLocalToIso(value: string): string {
  return new Date(value).toISOString();
}

export function defaultExpiresLocalValue(): string {
  const date = new Date();
  date.setDate(date.getDate() + 90);
  return toDatetimeLocalValue(date);
}
