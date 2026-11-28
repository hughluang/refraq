import { NextRequest } from "next/server";

import {
  mcpProxyTimeoutMs,
  mcpUpstreamUrl,
  proxyMcpPost,
} from "@/lib/mcp-proxy";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export function GET(request: NextRequest): Promise<Response> {
  return proxyMcpPost(
    request,
    mcpUpstreamUrl(request.url),
    mcpProxyTimeoutMs(),
  );
}

export function POST(request: NextRequest): Promise<Response> {
  return proxyMcpPost(
    request,
    mcpUpstreamUrl(request.url),
    mcpProxyTimeoutMs(),
  );
}

export function DELETE(request: NextRequest): Promise<Response> {
  return proxyMcpPost(
    request,
    mcpUpstreamUrl(request.url),
    mcpProxyTimeoutMs(),
  );
}
