import { describe, expect, it } from "vitest";

import { Instant } from "@/lib/instant";
import { instantToWall, wallToInstant } from "@/lib/wall-time";

describe("instantToWall", () => {
  it("maps null and absent to empty", () => {
    expect(instantToWall(null, "UTC")).toBeNull();
    expect(instantToWall(undefined, "UTC")).toBeNull();
  });

  it("reads a received Instant string and rejects a calendar date", () => {
    expect(instantToWall("2026-10-11T16:00:00Z", "Asia/Shanghai")).toBe(
      "2026-10-12 00:00:00",
    );
    expect(instantToWall("2026-10-11", "UTC")).toBeNull();
  });

  it("renders the Instant as wall time in the given zone", () => {
    expect(instantToWall(Instant.parse("2026-10-11T16:00:00Z"), "Asia/Shanghai")).toBe(
      "2026-10-12 00:00:00",
    );
    expect(instantToWall(Instant.parse("2026-10-12T00:00:00Z"), "UTC")).toBe(
      "2026-10-12 00:00:00",
    );
  });

  it("uses a T separator for datetime-local values", () => {
    expect(
      instantToWall(Instant.parse("2026-10-11T16:00:00Z"), "Asia/Shanghai", "T"),
    ).toBe("2026-10-12T00:00:00");
  });
});

describe("wallToInstant", () => {
  it("maps a cleared picker to null", () => {
    expect(wallToInstant(null, "UTC")).toBeNull();
    expect(wallToInstant("", "UTC")).toBeNull();
  });

  it("converts wall time to a UTC Instant", () => {
    expect(wallToInstant("2026-10-12 00:00:00", "Asia/Shanghai")).toBe(
      "2026-10-11T16:00:00Z",
    );
    expect(wallToInstant("2026-10-12 00:00", "UTC")).toBe("2026-10-12T00:00:00Z");
  });

  it("submits a UTC wall clock as second-precision Z", () => {
    expect(wallToInstant("2026-10-11 06:00:29", "UTC")).toBe("2026-10-11T06:00:29Z");
    expect(wallToInstant("2026-10-11 14:00:29", "Asia/Shanghai")).toBe(
      "2026-10-11T06:00:29Z",
    );
  });

  it("round-trips across a DST offset change", () => {
    const wall = "2026-07-01 09:30:00";
    const instant = wallToInstant(wall, "America/New_York");
    expect(instant).toBe("2026-07-01T13:30:00Z");
    expect(instantToWall(Instant.parse(instant!), "America/New_York")).toBe(wall);
  });

  it("resolves a wall time skipped by spring-forward to a later instant", () => {
    expect(wallToInstant("2026-03-08 02:30:00", "America/New_York")).toBe(
      "2026-03-08T07:30:00Z",
    );
  });

  it("keeps a typed 10:00 when the entry zone is Asia/Shanghai", () => {
    const stored = wallToInstant("2026-10-20T10:00", "Asia/Shanghai");
    expect(stored).toBe("2026-10-20T02:00:00Z");
    expect(instantToWall(Instant.parse(stored!), "Asia/Shanghai", "T")).toBe(
      "2026-10-20T10:00:00",
    );
  });
});
