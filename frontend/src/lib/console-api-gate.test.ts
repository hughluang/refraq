import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { isConsoleBlockedApiPath } from "@/lib/console-api-gate";

describe("console API gate", () => {
  it("blocks only /api/metrics", () => {
    expect(isConsoleBlockedApiPath("/api/metrics")).toBe(true);
    expect(isConsoleBlockedApiPath("/api/metrics/")).toBe(true);
    expect(isConsoleBlockedApiPath("/api/readyz")).toBe(false);
    expect(isConsoleBlockedApiPath("/api/healthz")).toBe(false);
    expect(isConsoleBlockedApiPath("/api/sources")).toBe(false);
    expect(isConsoleBlockedApiPath("/metrics")).toBe(false);
  });

  it("is wired in proxy before the /api rewrite hop", () => {
    const proxySrc = readFileSync(resolve(__dirname, "../proxy.ts"), "utf8");
    expect(proxySrc).toContain("isConsoleBlockedApiPath");
    expect(proxySrc).toContain("status: 404");
  });
});
