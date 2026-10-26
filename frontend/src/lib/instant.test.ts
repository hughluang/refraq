import { describe, expect, it } from "vitest";

import { Instant } from "@/lib/instant";

describe("Instant.parse", () => {
  it("accepts UTC Z and a numeric offset", () => {
    expect(Instant.parse("2026-10-11T06:00:29Z").epochMs()).toBe(
      Date.parse("2026-10-11T06:00:29Z"),
    );
    expect(Instant.parse("2026-10-11T14:00:29+08:00").epochMs()).toBe(
      Date.parse("2026-10-11T06:00:29Z"),
    );
  });

  it("rejects a timestamp with no offset", () => {
    expect(() => Instant.parse("2026-10-11T06:00:29")).toThrow(/invalid Instant/);
  });

  it("epochMsOf is null unless the text is a platform Instant", () => {
    expect(Instant.epochMsOf("2026-10-11T06:00:29Z")).toBe(
      Date.parse("2026-10-11T06:00:29Z"),
    );
    expect(Instant.epochMsOf("2026-10-11")).toBeNull();
    expect(Instant.epochMsOf("2026-10-11T06:00:29")).toBeNull();
  });

  it("serializes to ISO-8601", () => {
    expect(Instant.parse("2026-10-11T06:00:29Z").toJSON()).toBe(
      "2026-10-11T06:00:29.000Z",
    );
    expect(JSON.stringify(Instant.parse("2026-10-11T06:00:29Z"))).toBe(
      '"2026-10-11T06:00:29.000Z"',
    );
  });
});
