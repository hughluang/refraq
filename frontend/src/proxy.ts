import { NextResponse, type NextRequest } from "next/server";

const PROTECTED_PREFIXES = ["/console"];

const PUBLIC_PATHS = new Set(["/login", "/403"]);

function isProtectedPath(pathname: string): boolean {
  return PROTECTED_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  );
}

export function proxy(request: NextRequest): NextResponse {
  const { pathname, search } = request.nextUrl;

  if (PUBLIC_PATHS.has(pathname) || !isProtectedPath(pathname)) {
    return NextResponse.next();
  }

  if (request.cookies.get("refraq_sid")) {
    return NextResponse.next();
  }

  const loginUrl = request.nextUrl.clone();
  loginUrl.pathname = "/login";
  // Return path uses the `from` query param (consumed by LoginClient after login).
  loginUrl.search = `?from=${encodeURIComponent(pathname + search)}`;
  return NextResponse.redirect(loginUrl);
}

export const config = {
  matcher: ["/console", "/console/:path*"],
};
