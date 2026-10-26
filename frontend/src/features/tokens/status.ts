import type { TokenMetadata, TokenStatus } from "@/features/tokens/types";
import { Instant } from "@/lib/instant";
import { instantToWall } from "@/lib/wall-time";

const NINETY_DAYS_MS = 90 * 24 * 60 * 60 * 1000;

export function tokenStatus(
  token: TokenMetadata,
  now: Date = new Date(),
): TokenStatus {
  if (token.revoked_at) {
    return "deactivated";
  }
  const expires = Instant.epochMsOf(token.expires_at);
  if (expires !== null && expires <= now.getTime()) {
    return "expired";
  }
  return "active";
}

/** Default expiry as datetime-local text in the zone the form will submit. */
export function defaultExpiresWall(zone: string, now: number = Date.now()): string {
  const at = Instant.parse(new Date(now + NINETY_DAYS_MS).toISOString());
  return instantToWall(at, zone, "T") ?? "";
}
