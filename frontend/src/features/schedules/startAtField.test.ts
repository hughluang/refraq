import { describe, expect, it } from "vitest";

import {
  isAllowedStartAt,
  startAtToWall,
  startsInFuture,
  wallToStartAt,
} from "@/features/schedules/startAtField";

describe("startAtToWall", () => {
  it("maps null and absent to empty (start immediately)", () => {
    expect(startAtToWall(null, "UTC")).toBeNull();
    expect(startAtToWall(undefined, "UTC")).toBeNull();
    expect(startAtToWall("not a date", "UTC")).toBeNull();
  });

  it("renders the Instant as wall time in the Schedule Timezone", () => {
    expect(startAtToWall("2026-10-11T16:00:00Z", "Asia/Shanghai")).toBe(
      "2026-10-12 00:00:00",
    );
    expect(startAtToWall("2026-10-12T00:00:00Z", "UTC")).toBe(
      "2026-10-12 00:00:00",
    );
  });
});

describe("wallToStartAt", () => {
  it("maps a cleared picker to null", () => {
    expect(wallToStartAt(null, "UTC")).toBeNull();
    expect(wallToStartAt("", "UTC")).toBeNull();
  });

  it("converts Schedule Timezone wall time to a UTC Instant", () => {
    expect(wallToStartAt("2026-10-12 00:00:00", "Asia/Shanghai")).toBe(
      "2026-10-11T16:00:00.000Z",
    );
    expect(wallToStartAt("2026-10-12 00:00", "UTC")).toBe(
      "2026-10-12T00:00:00.000Z",
    );
  });

  it("round-trips across a DST offset change", () => {
    const wall = "2026-07-01 09:30:00";
    const instant = wallToStartAt(wall, "America/New_York");
    expect(instant).toBe("2026-07-01T13:30:00.000Z");
    expect(startAtToWall(instant, "America/New_York")).toBe(wall);
  });

  it("resolves a wall time skipped by spring-forward to a later instant", () => {
    expect(wallToStartAt("2026-03-08 02:30:00", "America/New_York")).toBe(
      "2026-03-08T07:30:00.000Z",
    );
  });
});

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
    expect(startsInFuture(null, now)).toBe(false);
  });
});
