import { NextRequest } from "next/server";

import {
  entityMcpProxyTimeoutMs,
  entityMcpUpstreamUrl,
  proxyMcpPost,
} from "@/lib/mcp-proxy";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export function GET(request: NextRequest): Promise<Response> {
  return proxyMcpPost(
    request,
    entityMcpUpstreamUrl(request.url),
    entityMcpProxyTimeoutMs(),
  );
}

export function POST(request: NextRequest): Promise<Response> {
  return proxyMcpPost(
    request,
    entityMcpUpstreamUrl(request.url),
    entityMcpProxyTimeoutMs(),
  );
}

export function DELETE(request: NextRequest): Promise<Response> {
  return proxyMcpPost(
    request,
    entityMcpUpstreamUrl(request.url),
    entityMcpProxyTimeoutMs(),
  );
}
