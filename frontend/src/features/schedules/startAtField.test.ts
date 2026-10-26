import { describe, expect, it } from "vitest";

import { isAllowedStartAt, startsInFuture } from "@/features/schedules/startAtField";

describe("isAllowedStartAt", () => {
  const now = Date.parse("2026-10-06T00:00:00Z");

  it("allows empty and past anchors", () => {
    expect(isAllowedStartAt(null, now)).toBe(true);
    expect(isAllowedStartAt("2020-01-01T00:00:00Z", now)).toBe(true);
  });

  it("rejects a start beyond the 2922-day horizon", () => {
    const limit = new Date(now + 252460800 * 1000).toISOString();
    const beyond = new Date(now + 252460801 * 1000).toISOString();
    expect(isAllowedStartAt(limit, now)).toBe(true);
    expect(isAllowedStartAt(beyond, now)).toBe(false);
  });
});

describe("startsInFuture", () => {
  const now = Date.parse("2026-10-06T00:00:00Z");

  it("is true only while the start is ahead", () => {
    expect(startsInFuture("2026-10-12T00:00:00Z", now)).toBe(true);
    expect(startsInFuture("2026-10-01T00:00:00Z", now)).toBe(false);
    expect(startsInFuture("2026-10-12", now)).toBe(false);
    expect(startsInFuture(null, now)).toBe(false);
  });
});
