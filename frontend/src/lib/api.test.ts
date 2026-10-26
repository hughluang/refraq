import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, apiClient } from "@/lib/api";

describe("apiClient Problem Details", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("reads detail and code and ignores message", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        return new Response(
          JSON.stringify({
            type: "urn:refraq:problem:AUTH_UNAUTHENTICATED",
            status: 401,
            detail: "Not signed in or session expired",
            code: "AUTH_UNAUTHENTICATED",
            request_id: "abc123",
            message: "should-not-be-used",
          }),
          {
            status: 401,
            headers: { "Content-Type": "application/problem+json" },
          },
        );
      }),
    );

    await expect(apiClient("/auth/me")).rejects.toEqual(
      expect.objectContaining({
        status: 401,
        code: "AUTH_UNAUTHENTICATED",
        detail: "Not signed in or session expired",
        requestId: "abc123",
      }),
    );
    const missing = await apiClient("/auth/me").then(
      () => null,
      (error: unknown) => error,
    );
    expect(missing).toBeInstanceOf(ApiError);
    expect((missing as ApiError).details).toBeUndefined();
  });

  it("keeps 422 details and leaves them out of extensions", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        return new Response(
          JSON.stringify({
            type: "urn:refraq:problem:REQUEST_INVALID",
            status: 422,
            detail: "Request validation failed",
            code: "REQUEST_INVALID",
            request_id: "rid-422",
            details: [
              {
                field: "account",
                code: "VALUE_MISSING",
                message: "Field required",
                input: "should-not-be-kept",
              },
            ],
            retry_after: 3,
          }),
          {
            status: 422,
            headers: { "Content-Type": "application/problem+json" },
          },
        );
      }),
    );

    await expect(apiClient("/users")).rejects.toMatchObject({
      status: 422,
      code: "REQUEST_INVALID",
      detail: "Request validation failed",
      requestId: "rid-422",
      details: [{ field: "account", code: "VALUE_MISSING", message: "Field required" }],
      extensions: { retry_after: 3 },
    });
  });

  it("keeps an empty details list and drops a non-list", async () => {
    const fetchMock = vi.fn(async (url: string) => {
      const details = String(url).endsWith("/empty") ? [] : "nope";
      return new Response(
        JSON.stringify({
          status: 422,
          detail: "Request validation failed",
          code: "REQUEST_INVALID",
          details,
        }),
        { status: 422, headers: { "Content-Type": "application/problem+json" } },
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(apiClient("/empty")).rejects.toMatchObject({ details: [] });
    const blank = await apiClient("/blank").then(
      () => null,
      (error: unknown) => error,
    );
    expect(blank).toBeInstanceOf(ApiError);
    expect((blank as ApiError).details).toBeUndefined();
  });

  it("returns success JSON for an operation that is not in the time table", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        return new Response(
          JSON.stringify({
            items: [{ round: 1, seq: 2 }],
            total: 1,
            limit: 50,
            offset: 0,
          }),
          {
            status: 200,
            headers: {
              "Content-Type": "application/json",
              "X-Request-ID": "req-rounds",
            },
          },
        );
      }),
    );

    await expect(
      apiClient("/channels/chn_1/runs/job_1/executions/4/rounds?limit=50"),
    ).resolves.toEqual({
      items: [{ round: 1, seq: 2 }],
      total: 1,
      limit: 50,
      offset: 0,
    });
  });

  it("returns an illegal Instant string inside success JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        return new Response(
          JSON.stringify({ items: [{ last_login_at: "yesterday" }] }),
          {
            status: 200,
            headers: {
              "Content-Type": "application/json",
              "X-Request-ID": "req-contract",
            },
          },
        );
      }),
    );

    await expect(apiClient("/users")).resolves.toEqual({
      items: [{ last_login_at: "yesterday" }],
    });
  });

  it("does not read a 204 body", async () => {
    const response = new Response(null, { status: 204 });
    const json = vi.spyOn(response, "json");
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => response),
    );

    await expect(apiClient("/tokens/tok_1", { method: "DELETE" })).resolves.toBeUndefined();
    expect(json).not.toHaveBeenCalled();
  });

  it("does not replay a failed write", async () => {
    const fetchMock = vi.fn(async () => {
      return new Response(
        JSON.stringify({
          status: 422,
          detail: "Request validation failed",
          code: "REQUEST_INVALID",
          request_id: "rid-write",
        }),
        { status: 422, headers: { "Content-Type": "application/problem+json" } },
      );
    });
    vi.stubGlobal("fetch", fetchMock);

    await expect(
      apiClient("/tokens", { method: "POST", body: "{}" }),
    ).rejects.toMatchObject({
      status: 422,
      code: "REQUEST_INVALID",
      requestId: "rid-write",
    });
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("aborts when timeoutMs elapses", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn((_url: string, init?: RequestInit) => {
        return new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            reject(init.signal?.reason ?? new DOMException("Aborted", "AbortError"));
          });
        });
      }),
    );

    await expect(apiClient("/auth/me", { timeoutMs: 5 })).rejects.toThrow();
  });
});

describe("apiClient session expiry", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.resetModules();
  });

  async function loadApiClient() {
    vi.resetModules();
    return import("@/lib/api");
  }

  function stubWindow(pathname: string) {
    const storage = new Map<string, string>();
    const assign = vi.fn();
    vi.stubGlobal("window", {
      sessionStorage: {
        getItem: (key: string) => storage.get(key) ?? null,
        setItem: (key: string, value: string) => {
          storage.set(key, value);
        },
        removeItem: (key: string) => {
          storage.delete(key);
        },
      },
      location: { assign, pathname, search: "" },
    });
    return assign;
  }

  function rejectUnauthenticated() {
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        return new Response(
          JSON.stringify({
            status: 401,
            detail: "Not signed in or session expired",
            code: "AUTH_UNAUTHENTICATED",
          }),
          { status: 401, headers: { "Content-Type": "application/problem+json" } },
        );
      }),
    );
  }

  it("hard-navigates once from a protected page", async () => {
    const assign = stubWindow("/console/jobs");
    rejectUnauthenticated();
    const { apiClient: client, ApiError: ClientError } = await loadApiClient();

    await expect(client("/jobs")).rejects.toBeInstanceOf(ClientError);
    await expect(client("/jobs")).rejects.toBeInstanceOf(ClientError);

    expect(assign).toHaveBeenCalledTimes(1);
    expect(assign).toHaveBeenCalledWith(
      "/login?from=%2Fconsole%2Fjobs&error=AUTH_SESSION_EXPIRED",
    );
  });

  it("does not redirect a password failure", async () => {
    const assign = stubWindow("/login");
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        return new Response(
          JSON.stringify({
            status: 401,
            detail: "Invalid account or password",
            code: "AUTH_INVALID_CREDENTIALS",
          }),
          { status: 401, headers: { "Content-Type": "application/problem+json" } },
        );
      }),
    );

    const { apiClient: client, ApiError: ClientError } = await loadApiClient();
    await expect(client("/auth/login", { method: "POST" })).rejects.toBeInstanceOf(
      ClientError,
    );
    expect(assign).not.toHaveBeenCalled();
  });

  it("does not redirect when the document is already /login", async () => {
    const assign = stubWindow("/login");
    rejectUnauthenticated();

    const { apiClient: client, ApiError: ClientError } = await loadApiClient();
    await expect(client("/auth/me")).rejects.toBeInstanceOf(ClientError);
    expect(assign).not.toHaveBeenCalled();
  });
});
