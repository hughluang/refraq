import { afterEach, describe, expect, it, vi } from "vitest";

import {
  loginRedirectAfterSessionExpiry,
  resolveFromPath,
} from "./return-path";

describe("resolveFromPath", () => {
  it("keeps same-origin relative paths", () => {
    expect(resolveFromPath("/console/users")).toBe("/console/users");
    expect(resolveFromPath("/console?tab=pending")).toBe("/console?tab=pending");
    expect(resolveFromPath("/")).toBe("/");
  });

  it("falls back when the value is absent or not a path", () => {
    expect(resolveFromPath(null)).toBe("/console");
    expect(resolveFromPath("")).toBe("/console");
    expect(resolveFromPath("console")).toBe("/console");
    expect(resolveFromPath("x")).toBe("/console");
  });

  it.each([
    "//evil.example",
    "https://evil.example",
    "/\\evil.example",
    "/safe\\evil",
    "/%2f%2fevil.example",
    "/%5cevil.example",
    "/safe\x00evil",
    "/safe%00evil",
    "/console#@evil.example",
    "/%zz",
  ])("rejects cross-origin or malformed value %j", (value) => {
    expect(resolveFromPath(value)).toBe("/console");
  });
});

describe("loginRedirectAfterSessionExpiry", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("keeps the validated from path and adds the session-ended error", () => {
    vi.stubGlobal("window", {
      location: { pathname: "/console/jobs", search: "?open=1" },
    });
    expect(loginRedirectAfterSessionExpiry()).toBe(
      "/login?from=%2Fconsole%2Fjobs%3Fopen%3D1&error=AUTH_SESSION_EXPIRED",
    );
  });
});
