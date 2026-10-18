import { ApiContractError, decodeResponseInstants } from "@/lib/instant";
import { isProtectedPath } from "@/lib/route-scope";

const baseUrl = process.env.NEXT_PUBLIC_REFRAQ_API_BASE_URL || "/api";

const SESSION_EXPIRY_SKIP_PATHS = new Set(["/auth/login", "/auth/logout"]);

/** One `details[]` entry on a 422 Problem Details body. */
export type ApiFieldDetail = {
  field?: string;
  message?: string;
  code?: string;
};

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: string;
  readonly requestId: string | null;
  /**
   * 422 `details`. An array (possibly empty) when the body sends a list.
   * Undefined when the member is missing or not a list.
   */
  readonly details?: readonly ApiFieldDetail[];
  /** Domain members of the Problem Details body beyond the frozen ones. */
  readonly extensions: Record<string, unknown>;

  constructor(
    status: number,
    code: string,
    detail: string,
    requestId: string | null = null,
    extensions: Record<string, unknown> = {},
    details?: readonly ApiFieldDetail[],
  ) {
    super(`${code}: ${detail}`);
    this.status = status;
    this.code = code;
    this.detail = detail;
    this.requestId = requestId;
    this.details = details === undefined ? undefined : [...details];
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
  details?: unknown;
};

function isApiErrorBody(value: unknown): value is ApiErrorBody {
  return typeof value === "object" && value !== null;
}

function stringMember(value: unknown): string | undefined {
  return typeof value === "string" ? value : undefined;
}

function readFieldDetail(value: unknown): ApiFieldDetail | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  const detail: ApiFieldDetail = {};
  const field = stringMember(record.field);
  const message = stringMember(record.message);
  const code = stringMember(record.code);
  if (field !== undefined) detail.field = field;
  if (message !== undefined) detail.message = message;
  if (code !== undefined) detail.code = code;
  return detail;
}

/** Missing or non-list `details` stays undefined. A list is kept, including `[]`. */
function readDetails(body: ApiErrorBody): ApiFieldDetail[] | undefined {
  if (!Object.prototype.hasOwnProperty.call(body, "details")) return undefined;
  if (!Array.isArray(body.details)) return undefined;
  const details: ApiFieldDetail[] = [];
  for (const item of body.details) {
    const detail = readFieldDetail(item);
    if (detail) details.push(detail);
  }
  return details;
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
    return new ApiError(
      response.status,
      code,
      detail,
      requestId,
      extensions,
      readDetails(body),
    );
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
