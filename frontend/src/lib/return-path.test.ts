import { afterEach, describe, expect, it, vi } from "vitest";

import { loginRedirectWithFrom, resolveFromPath } from "@/lib/return-path";

describe("resolveFromPath", () => {
  it("defaults empty values to /console", () => {
    expect(resolveFromPath(null)).toBe("/console");
    expect(resolveFromPath(undefined)).toBe("/console");
    expect(resolveFromPath("")).toBe("/console");
  });

  it("rejects protocol-relative and non-relative paths", () => {
    expect(resolveFromPath("//evil.com")).toBe("/console");
    expect(resolveFromPath("https://evil.com")).toBe("/console");
  });

  it("keeps same-origin relative paths", () => {
    expect(resolveFromPath("/console/users")).toBe("/console/users");
  });
});

describe("loginRedirectWithFrom", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("returns bare /login when already on /login", () => {
    vi.stubGlobal("window", {
      location: { pathname: "/login", search: "" },
    });
    expect(loginRedirectWithFrom()).toBe("/login");
  });

  it("returns bare /login when already on /login with a from query", () => {
    vi.stubGlobal("window", {
      location: { pathname: "/login", search: "?from=%2Fconsole" },
    });
    expect(loginRedirectWithFrom()).toBe("/login");
  });

  it("encodes the current console path as from", () => {
    vi.stubGlobal("window", {
      location: { pathname: "/console/users", search: "?q=1" },
    });
    expect(loginRedirectWithFrom()).toBe("/login?from=%2Fconsole%2Fusers%3Fq%3D1");
  });
});
