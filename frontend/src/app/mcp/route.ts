import { NextRequest } from "next/server";

import {
  mcpProxyTimeoutMs,
  mcpUpstreamUrl,
  proxyMcpPost,
} from "@/lib/mcp-proxy";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export function POST(request: NextRequest): Promise<Response> {
  return proxyMcpPost(
    request,
    mcpUpstreamUrl(request.url),
    mcpProxyTimeoutMs(),
  );
}
