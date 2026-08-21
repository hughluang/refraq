import { describe, expect, it } from "vitest";

import { browserFacingProtoFromEnv } from "./browser-facing-proto";

describe("browserFacingProtoFromEnv", () => {
  it("defaults to http when unset", () => {
    expect(browserFacingProtoFromEnv({})).toBe("http");
  });

  it("ignores empty or unknown values", () => {
    expect(browserFacingProtoFromEnv({ REFRAQ_BROWSER_FACING_PROTO: "" })).toBe(
      "http",
    );
    expect(
      browserFacingProtoFromEnv({ REFRAQ_BROWSER_FACING_PROTO: "ftp" }),
    ).toBe("http");
  });

  it("accepts explicit http and https", () => {
    expect(
      browserFacingProtoFromEnv({ REFRAQ_BROWSER_FACING_PROTO: "https" }),
    ).toBe("https");
    expect(
      browserFacingProtoFromEnv({ REFRAQ_BROWSER_FACING_PROTO: " HTTP " }),
    ).toBe("http");
  });
});
