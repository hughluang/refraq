import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

import { isConsoleBlockedApiPath } from "@/lib/console-api-gate";
import {
  entityMcpProxyTimeoutMs,
  entityMcpUpstreamUrl,
  guardProxiedBody,
  isMcpPassthroughPath,
  mcpProxyTimeoutMs,
  mcpUpstreamUrl,
} from "@/lib/mcp-proxy";
import { isProtectedPath } from "@/lib/route-scope";

describe("mcp proxy helpers", () => {
  it("passes the product path and not readyz", () => {
    expect(isMcpPassthroughPath("/mcp")).toBe(true);
    expect(isMcpPassthroughPath("/mcp/")).toBe(true);
    expect(isMcpPassthroughPath("/mcp/entity")).toBe(true);
    expect(isProtectedPath("/mcp/entity")).toBe(false);
    expect(isMcpPassthroughPath("/readyz")).toBe(false);
    expect(isMcpPassthroughPath("/metrics")).toBe(false);
    expect(isMcpPassthroughPath("/api/mcp/catalog")).toBe(false);
    expect(isProtectedPath("/mcp")).toBe(false);
    expect(isConsoleBlockedApiPath("/api/metrics")).toBe(true);
    expect(isConsoleBlockedApiPath("/api/readyz")).toBe(false);
  });

  it("streams /mcp through a Route Handler, not a rewrite", () => {
    const route = readFileSync(
      resolve(__dirname, "../app/mcp/route.ts"),
      "utf8",
    );
    const proxy = readFileSync(resolve(__dirname, "./mcp-proxy.ts"), "utf8");
    expect(proxy).toContain('duplex?: "half"');
    expect(proxy).toContain('init.duplex = "half"');
    expect(proxy).toContain("X-Accel-Buffering");
    expect(proxy).toContain("mcp_upstream_unavailable");
    expect(route).toContain("proxyMcpPost");
    expect(route).toContain("mcpUpstreamUrl");
    expect(route).toContain("mcpProxyTimeoutMs");
    expect(route).toMatch(/export function POST/);
    expect(route).not.toMatch(/export function GET/);
    expect(route).not.toMatch(/export function DELETE/);
    const nextConfig = readFileSync(
      resolve(__dirname, "../../next.config.mjs"),
      "utf8",
    );
    expect(nextConfig).not.toMatch(/source:\s*["']\/mcp/);
    expect(nextConfig).not.toMatch(/source:\s*["']\/metrics/);
  });

  it("waits the query timeout ceiling plus margin", () => {
    expect(mcpProxyTimeoutMs()).toBe(3_605_000);
  });

  it("targets the MCP process /mcp, never readyz", () => {
    expect(
      mcpUpstreamUrl("https://console.example.com/mcp", {
        REFRAQ_MCP_UPSTREAM: "http://mcp:8001/",
      }),
    ).toBe("http://mcp:8001/mcp");
  });

  it("targets the entity MCP process /mcp/entity", () => {
    expect(entityMcpProxyTimeoutMs()).toBe(305_000);
    expect(mcpProxyTimeoutMs()).toBe(3_605_000);
    expect(
      entityMcpUpstreamUrl("https://console.example.com/mcp/entity", {
        REFRAQ_ENTITY_MCP_UPSTREAM: "http://entity-mcp:8002/",
      }),
    ).toBe("http://entity-mcp:8002/mcp/entity");
    expect(
      entityMcpUpstreamUrl("https://console.example.com/mcp/entity?x=1", {}),
    ).toBe("http://127.0.0.1:8002/mcp/entity?x=1");
    const route = readFileSync(
      resolve(__dirname, "../app/mcp/entity/route.ts"),
      "utf8",
    );
    expect(route).toMatch(/export function POST/);
    expect(route).not.toMatch(/export function GET/);
    expect(route).not.toMatch(/export function DELETE/);
    expect(route).toContain("entityMcpUpstreamUrl");
    expect(route).toContain("entityMcpProxyTimeoutMs");
    expect(route).toContain("proxyMcpPost");
  });

  it("logs one line and rejects when the upstream body errors", async () => {
    const body = new ReadableStream<Uint8Array>({
      pull(controller) {
        controller.error(
          Object.assign(new Error("aborted"), { name: "TimeoutError" }),
        );
      },
    });
    const lines: string[] = [];
    const guarded = guardProxiedBody(
      body,
      { method: "POST", path: "/mcp", startedAtMs: Date.now() - 50 },
      (line) => lines.push(line),
    );
    expect(guarded).not.toBeNull();
    await expect(guarded!.getReader().read()).rejects.toMatchObject({
      name: "TimeoutError",
    });
    expect(lines).toEqual([
      expect.stringMatching(
        /^mcp proxy body aborted method=POST path=\/mcp elapsed_ms=\d+ error=TimeoutError$/,
      ),
    ]);
  });

  it("forwards a completed upstream body without logging", async () => {
    const payload = new Uint8Array([7]);
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(payload);
        controller.close();
      },
    });
    const lines: string[] = [];
    const guarded = guardProxiedBody(
      body,
      { method: "POST", path: "/mcp", startedAtMs: Date.now() },
      (line) => lines.push(line),
    );
    expect(guarded).not.toBeNull();
    const reader = guarded!.getReader();
    const first = await reader.read();
    expect(first.done).toBe(false);
    expect(first.value).toEqual(payload);
    const rest = await reader.read();
    expect(rest).toEqual({ done: true, value: undefined });
    expect(lines).toEqual([]);
  });
});
