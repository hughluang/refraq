import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import {
  isMcpPassthroughPath,
  mcpProxyTimeoutMs,
  mcpUpstreamOrigin,
  mcpUpstreamUrl,
} from "@/lib/mcp-proxy";
import { isProtectedPath } from "@/lib/route-scope";

describe("mcp proxy helpers", () => {
  it("passes the product path and not readyz", () => {
    expect(isMcpPassthroughPath("/mcp")).toBe(true);
    expect(isMcpPassthroughPath("/mcp/")).toBe(true);
    expect(isMcpPassthroughPath("/readyz")).toBe(false);
    expect(isMcpPassthroughPath("/api/mcp/catalog")).toBe(false);
    expect(isProtectedPath("/mcp")).toBe(false);
  });

  it("streams /mcp through a Route Handler, not a rewrite", () => {
    const route = readFileSync(
      resolve(__dirname, "../app/mcp/route.ts"),
      "utf8",
    );
    expect(route).toContain('duplex?: "half"');
    expect(route).toContain('init.duplex = "half"');
    expect(route).toContain("X-Accel-Buffering");
    const nextConfig = readFileSync(
      resolve(__dirname, "../../next.config.mjs"),
      "utf8",
    );
    expect(nextConfig).not.toMatch(/source:\s*["']\/mcp/);
  });

  it("waits at least the query timeout plus margin", () => {
    expect(mcpProxyTimeoutMs({ REFRAQ_QUERY_TIMEOUT_SEC: "30" })).toBe(35_000);
    expect(mcpProxyTimeoutMs({ REFRAQ_QUERY_TIMEOUT_SEC: "45" })).toBe(50_000);
    expect(mcpProxyTimeoutMs({})).toBe(35_000);
  });

  it("rejects a non-positive or non-numeric query timeout", () => {
    expect(() => mcpProxyTimeoutMs({ REFRAQ_QUERY_TIMEOUT_SEC: "foo" })).toThrow(
      /REFRAQ_QUERY_TIMEOUT_SEC/,
    );
    expect(() => mcpProxyTimeoutMs({ REFRAQ_QUERY_TIMEOUT_SEC: "0" })).toThrow(
      /REFRAQ_QUERY_TIMEOUT_SEC/,
    );
    expect(() => mcpProxyTimeoutMs({ REFRAQ_QUERY_TIMEOUT_SEC: "-1" })).toThrow(
      /REFRAQ_QUERY_TIMEOUT_SEC/,
    );
  });

  it("targets the MCP process /mcp, never readyz", () => {
    expect(mcpUpstreamOrigin({ REFRAQ_MCP_UPSTREAM: "http://mcp:8001/" })).toBe(
      "http://mcp:8001",
    );
    expect(
      mcpUpstreamUrl("https://console.example.com/mcp", {
        REFRAQ_MCP_UPSTREAM: "http://mcp:8001",
      }),
    ).toBe("http://mcp:8001/mcp");
  });
});
