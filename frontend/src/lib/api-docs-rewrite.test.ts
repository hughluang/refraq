import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { isProtectedPath } from "@/lib/route-scope";

describe("OpenAPI docs rewrites", () => {
  it("proxies /docs and /openapi.json on the web origin, not under /api", () => {
    const nextConfig = readFileSync(
      resolve(__dirname, "../../next.config.mjs"),
      "utf8",
    );
    expect(nextConfig).toMatch(/source:\s*["']\/docs\/:path\*["']/);
    expect(nextConfig).not.toMatch(/source:\s*["']\/docs["']/);
    expect(nextConfig).toMatch(/source:\s*["']\/openapi\.json["']/);
    expect(nextConfig).not.toMatch(/source:\s*["']\/redoc/);
    expect(nextConfig).not.toMatch(/source:\s*["']\/api\/docs/);
    expect(isProtectedPath("/docs")).toBe(false);
    expect(isProtectedPath("/openapi.json")).toBe(false);
  });
});
