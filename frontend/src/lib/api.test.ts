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
