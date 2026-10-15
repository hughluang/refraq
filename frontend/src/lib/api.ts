import { ApiContractError, decodeResponseInstants } from "@/lib/instant";
import { isProtectedPath } from "@/lib/route-scope";

const baseUrl = process.env.NEXT_PUBLIC_REFRAQ_API_BASE_URL || "/api";

const SESSION_EXPIRY_SKIP_PATHS = new Set(["/auth/login", "/auth/logout"]);

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: string;
  readonly requestId: string | null;
  /** Domain members of the Problem Details body beyond the frozen ones. */
  readonly extensions: Record<string, unknown>;

  constructor(
    status: number,
    code: string,
    detail: string,
    requestId: string | null = null,
    extensions: Record<string, unknown> = {},
  ) {
    super(`${code}: ${detail}`);
    this.status = status;
    this.code = code;
    this.detail = detail;
    this.requestId = requestId;
    this.extensions = extensions;
  }
}

const PROBLEM_FIXED_MEMBERS = new Set([
  "type",
  "status",
  "detail",
  "code",
  "request_id",
  "details",
  "title",
  "instance",
]);

type ApiErrorBody = {
  code?: unknown;
  detail?: unknown;
  request_id?: unknown;
};

function isApiErrorBody(value: unknown): value is ApiErrorBody {
  return typeof value === "object" && value !== null;
}

async function parseError(response: Response): Promise<ApiError> {
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }

  if (isApiErrorBody(body)) {
    const code =
      typeof body.code === "string" && body.code.length > 0
        ? body.code
        : "API_UNKNOWN_ERROR";
    const detail =
      typeof body.detail === "string" && body.detail.length > 0
        ? body.detail
        : response.statusText;
    const requestId =
      typeof body.request_id === "string" && body.request_id.length > 0
        ? body.request_id
        : null;
    const extensions: Record<string, unknown> = {};
    for (const [key, value] of Object.entries(body)) {
      if (!PROBLEM_FIXED_MEMBERS.has(key)) extensions[key] = value;
    }
    return new ApiError(response.status, code, detail, requestId, extensions);
  }

  return new ApiError(
    response.status,
    "API_UNKNOWN_ERROR",
    response.statusText || "Request failed",
  );
}

export function isSessionExpiredError(error: unknown): boolean {
  return error instanceof ApiError && error.code === "AUTH_UNAUTHENTICATED";
}

function shouldRedirectSessionExpiry(path: string, error: ApiError): boolean {
  if (error.code !== "AUTH_UNAUTHENTICATED") return false;
  if (SESSION_EXPIRY_SKIP_PATHS.has(path)) return false;
  if (typeof window === "undefined") return false;
  return isProtectedPath(window.location.pathname);
}

export type ApiRequestInit = RequestInit & {
  timeoutMs?: number;
};

function requestSignal(init?: ApiRequestInit): AbortSignal | undefined {
  if (!init) {
    return undefined;
  }
  const timeoutSignal =
    init.timeoutMs !== undefined ? AbortSignal.timeout(init.timeoutMs) : undefined;
  if (timeoutSignal && init.signal) {
    return AbortSignal.any([timeoutSignal, init.signal]);
  }
  return timeoutSignal ?? init.signal ?? undefined;
}

export async function apiClient<T = unknown>(
  path: string,
  init?: ApiRequestInit,
): Promise<T> {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const { timeoutMs: _timeoutMs, ...fetchInit } = init ?? {};
  const response = await fetch(`${baseUrl}${normalizedPath}`, {
    credentials: "include",
    ...fetchInit,
    signal: requestSignal(init),
  });

  if (!response.ok) {
    const error = await parseError(response);
    if (shouldRedirectSessionExpiry(normalizedPath, error)) {
      const { expireClientSession } = await import("@/lib/session-expiry");
      expireClientSession();
    }
    throw error;
  }

  if (response.status === 204) {
    return undefined as T;
  }

  const method = (fetchInit.method ?? "GET").toUpperCase();
  const body: unknown = await response.json();
  try {
    return decodeResponseInstants(method, normalizedPath, body) as T;
  } catch (err) {
    if (!(err instanceof ApiContractError)) throw err;
    const requestId = response.headers.get("x-request-id");
    throw new ApiError(
      response.status,
      "API_CONTRACT_INVALID",
      err.message,
      requestId && requestId.length > 0 ? requestId : null,
    );
  }
}
