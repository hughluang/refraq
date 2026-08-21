import { createProxy } from "next-i18next/proxy";
import { NextRequest, NextResponse } from "next/server";

import i18nConfig from "../i18n.config";
import { browserFacingProtoFromEnv } from "./lib/browser-facing-proto";
import { isProtectedPath } from "./lib/route-scope";

const PUBLIC_PATHS = new Set(["/login", "/403"]);

const i18nProxy = createProxy(i18nConfig);

/** Strip Accept-Language so detection is cookie → fallback only. */
function requestWithoutAcceptLanguage(request: NextRequest): NextRequest {
  const headers = new Headers(request.headers);
  headers.delete("accept-language");
  return new NextRequest(request.url, {
    method: request.method,
    headers,
  });
}

function copyCookies(from: NextResponse, to: NextResponse): void {
  for (const cookie of from.cookies.getAll()) {
    to.cookies.set(cookie);
  }
}

/** Stamp browser-facing proto for the API rewrite; never pass client values. */
function apiRewriteWithTrustedProto(request: NextRequest): NextResponse {
  const headers = new Headers(request.headers);
  headers.set("x-forwarded-proto", browserFacingProtoFromEnv());
  return NextResponse.next({
    request: { headers },
  });
}

export function proxy(request: NextRequest): NextResponse {
  if (request.nextUrl.pathname.startsWith("/api")) {
    return apiRewriteWithTrustedProto(request);
  }

  const i18nResponse = i18nProxy(requestWithoutAcceptLanguage(request));

  const { pathname, search } = request.nextUrl;

  if (PUBLIC_PATHS.has(pathname) || !isProtectedPath(pathname)) {
    return i18nResponse;
  }

  if (request.cookies.get("refraq_sid")) {
    return i18nResponse;
  }

  const loginUrl = request.nextUrl.clone();
  loginUrl.pathname = "/login";
  // Return path uses the `from` query param (consumed by LoginClient after login).
  loginUrl.search = `?from=${encodeURIComponent(pathname + search)}`;
  const redirect = NextResponse.redirect(loginUrl);
  copyCookies(i18nResponse, redirect);
  return redirect;
}

export const config = {
  // Include `/api` so the rewrite hop can overwrite `X-Forwarded-Proto`.
  // Exclude all `/_next/*` (including webpack-hmr websocket) so Turbopack HMR
  // is not broken by this proxy; static/image alone is not enough.
  matcher: ["/((?!_next/|favicon.ico).*)"],
};
