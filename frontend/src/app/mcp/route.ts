import { NextRequest } from "next/server";

import { mcpProxyTimeoutMs, mcpUpstreamUrl } from "@/lib/mcp-proxy";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

async function proxyMcp(request: NextRequest): Promise<Response> {
  const target = mcpUpstreamUrl(request.url);
  const headers = new Headers(request.headers);
  headers.delete("host");
  headers.delete("connection");
  headers.delete("content-length");
  headers.delete("transfer-encoding");
  const method = request.method.toUpperCase();
  const init: RequestInit & { duplex?: "half" } = {
    method,
    headers,
    redirect: "manual",
    signal: AbortSignal.timeout(mcpProxyTimeoutMs()),
  };
  if (method !== "GET" && method !== "HEAD") {
    init.body = request.body;
    init.duplex = "half";
  }
  try {
    const upstream = await fetch(target, init);
    const out = new Headers(upstream.headers);
    out.set("X-Accel-Buffering", "no");
    return new Response(upstream.body, {
      status: upstream.status,
      statusText: upstream.statusText,
      headers: out,
    });
  } catch {
    return new Response(JSON.stringify({ error: "mcp_upstream_unavailable" }), {
      status: 502,
      headers: { "content-type": "application/json", "X-Accel-Buffering": "no" },
    });
  }
}

export function GET(request: NextRequest): Promise<Response> {
  return proxyMcp(request);
}

export function POST(request: NextRequest): Promise<Response> {
  return proxyMcp(request);
}

export function DELETE(request: NextRequest): Promise<Response> {
  return proxyMcp(request);
}
