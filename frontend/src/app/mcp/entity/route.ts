import { NextRequest } from "next/server";

import {
  entityMcpProxyTimeoutMs,
  entityMcpUpstreamUrl,
  proxyMcpPost,
} from "@/lib/mcp-proxy";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

export function POST(request: NextRequest): Promise<Response> {
  return proxyMcpPost(
    request,
    entityMcpUpstreamUrl(request.url),
    entityMcpProxyTimeoutMs(),
  );
}
