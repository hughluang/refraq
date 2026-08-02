const baseUrl = process.env.NEXT_PUBLIC_REFRAQ_API_BASE_URL || "/api";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly detail: string;

  constructor(status: number, code: string, detail: string) {
    super(`${code}: ${detail}`);
    this.status = status;
    this.code = code;
    this.detail = detail;
  }
}

type ApiErrorBody = {
  code?: unknown;
  message?: unknown;
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
    const message =
      typeof body.message === "string" && body.message.length > 0
        ? body.message
        : response.statusText;
    return new ApiError(response.status, code, message);
  }

  return new ApiError(
    response.status,
    "API_UNKNOWN_ERROR",
    response.statusText || "Request failed",
  );
}

export async function apiClient<T = unknown>(
  path: string,
  init?: RequestInit,
): Promise<T> {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  const response = await fetch(`${baseUrl}${normalizedPath}`, {
    credentials: "include",
    ...init,
  });

  if (!response.ok) {
    throw await parseError(response);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}
