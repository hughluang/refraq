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
    await expect(apiClient("/auth/me")).rejects.toBeInstanceOf(ApiError);
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
