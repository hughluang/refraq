const baseUrl = process.env.NEXT_PUBLIC_REFRAQ_API_BASE_URL || "/api";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: string;
  readonly requestId: string | null;

  constructor(
    status: number,
    code: string,
    detail: string,
    requestId: string | null = null,
  ) {
    super(`${code}: ${detail}`);
    this.status = status;
    this.code = code;
    this.detail = detail;
    this.requestId = requestId;
  }
}

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
    return new ApiError(response.status, code, detail, requestId);
  }

  return new ApiError(
    response.status,
    "API_UNKNOWN_ERROR",
    response.statusText || "Request failed",
  );
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
    throw await parseError(response);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}
