import { describe, expect, it } from "vitest";

import { ApiContractError, Instant, decodeResponseInstants } from "@/lib/instant";

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

  it("serializes to ISO-8601", () => {
    expect(Instant.parse("2026-10-11T06:00:29Z").toJSON()).toBe(
      "2026-10-11T06:00:29.000Z",
    );
    expect(JSON.stringify(Instant.parse("2026-10-11T06:00:29Z"))).toBe(
      '"2026-10-11T06:00:29.000Z"',
    );
  });
});

describe("decodeResponseInstants", () => {
  it("decodes declared paths and leaves null", () => {
    const body = decodeResponseInstants("GET", "/channels/ch_1/runs?limit=50", {
      items: [
        {
          job_id: "job_1",
          created_at: "2026-10-11T06:00:29Z",
          started_at: null,
          finished_at: "2026-10-11T06:01:00Z",
        },
      ],
      total: 1,
    }) as {
      items: { created_at: { epochMs(): number }; started_at: null; finished_at: { epochMs(): number } }[];
    };
    expect(body.items[0].created_at.epochMs()).toBe(Date.parse("2026-10-11T06:00:29Z"));
    expect(body.items[0].started_at).toBeNull();
    expect(body.items[0].finished_at.epochMs()).toBe(Date.parse("2026-10-11T06:01:00Z"));
  });

  it("throws when a declared value is not an Instant", () => {
    expect(() =>
      decodeResponseInstants("GET", "/channels/ch_1/runs", {
        items: [{ created_at: "yesterday", started_at: null, finished_at: null }],
      }),
    ).toThrow(ApiContractError);
  });

  it("passes through an operation with no Instant fields", () => {
    const body = { brand_names: { "en-US": "Acme" } };
    expect(decodeResponseInstants("GET", "/branding", body)).toBe(body);
  });

  it("rejects a path that is not in the OpenAPI document", () => {
    expect(() => decodeResponseInstants("GET", "/not-an-api", {})).toThrow(
      ApiContractError,
    );
  });
});
