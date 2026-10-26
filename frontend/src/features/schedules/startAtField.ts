import { MAX_CADENCE_SECONDS } from "@/features/schedules/intervalUnits";
import { Instant } from "@/lib/instant";

/** Empty (start immediately), any past anchor, or a future start within the cadence horizon. */
export function isAllowedStartAt(
  value: string | null,
  now: number = Date.now(),
): boolean {
  if (value === null) return true;
  const ms = Date.parse(value);
  return !Number.isNaN(ms) && ms <= now + MAX_CADENCE_SECONDS * 1000;
}

/** True while a Schedule Start is still ahead; a past one is only the anchor. */
export function startsInFuture(
  value: string | null | undefined,
  now: number = Date.now(),
): boolean {
  if (!value) return false;
  const ms = Instant.epochMsOf(value);
  return ms !== null && ms > now;
}
