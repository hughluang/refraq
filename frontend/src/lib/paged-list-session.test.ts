import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";
import type { OffsetPage } from "@/lib/pagination";
import {
  listErrorMessage,
  listErrorRequestId,
  loadPagedGeneration,
  syncResetPage,
} from "@/lib/paged-list-session";

function pageOf<T>(items: T[], total = items.length): OffsetPage<T> {
  return { items, total, limit: 50, offset: 0 };
}

describe("syncResetPage", () => {
  it("keeps the current page when the reset key is unchanged", () => {
    expect(
      syncResetPage({ resetKey: "a", previousKey: "a", page: 3 }),
    ).toEqual({ fetchPage: 3, shouldSetPage: false });
  });

  it("returns page 1 when the reset key changes", () => {
    expect(
      syncResetPage({ resetKey: "b", previousKey: "a", page: 1 }),
    ).toEqual({ fetchPage: 1, shouldSetPage: false });
    expect(
      syncResetPage({ resetKey: "b", previousKey: "a", page: 4 }),
    ).toEqual({ fetchPage: 1, shouldSetPage: true });
  });
});

describe("list error fields", () => {
  it("splits ApiError detail from requestId", () => {
    const err = new ApiError(500, "JOB_FAILED", "boom", "req-1");
    expect(listErrorMessage(err)).toBe("boom");
    expect(listErrorRequestId(err)).toBe("req-1");
  });

  it("stringifies a generic error without a request id", () => {
    expect(listErrorMessage(new Error("nope"))).toBe("Error: nope");
    expect(listErrorRequestId(new Error("nope"))).toBeNull();
  });
});

describe("loadPagedGeneration", () => {
  it("clears to disabled when the list is not enabled", () => {
    const result = loadPagedGeneration({
      started: 1,
      currentGeneration: () => 1,
      enabled: false,
      fetch: () => pageOf(["x"]),
      page: 1,
      pageSize: 50,
    });
    expect(result).toEqual({ kind: "disabled" });
  });

  it("returns a synchronous ok result for a local adapter", () => {
    const result = loadPagedGeneration({
      started: 2,
      currentGeneration: () => 2,
      enabled: true,
      fetch: (query) => pageOf(["a", "b"].slice(query.offset, query.offset + query.limit), 2),
      page: 1,
      pageSize: 50,
    });
    expect(result).toEqual({
      kind: "ok",
      page: pageOf(["a", "b"], 2),
    });
  });

  it("discards a slower generation after a newer load started", async () => {
    let current = 1;
    let resolveSlow: (page: OffsetPage<string>) => void = () => {};
    const slow = new Promise<OffsetPage<string>>((resolve) => {
      resolveSlow = resolve;
    });
    const pending = loadPagedGeneration({
      started: 1,
      currentGeneration: () => current,
      enabled: true,
      fetch: () => slow,
      page: 1,
      pageSize: 50,
    });
    current = 2;
    resolveSlow(pageOf(["stale"]));
    await expect(pending).resolves.toEqual({ kind: "stale" });
  });

  it("discards a late error from an older generation", async () => {
    let current = 1;
    let rejectSlow: (err: unknown) => void = () => {};
    const slow = new Promise<OffsetPage<string>>((_, reject) => {
      rejectSlow = reject;
    });
    const pending = loadPagedGeneration({
      started: 1,
      currentGeneration: () => current,
      enabled: true,
      fetch: () => slow,
      page: 1,
      pageSize: 50,
    });
    current = 2;
    rejectSlow(new ApiError(502, "UPSTREAM", "gone", "req-old"));
    await expect(pending).resolves.toEqual({ kind: "stale" });
  });

  it("returns error detail and requestId", async () => {
    const result = await loadPagedGeneration({
      started: 3,
      currentGeneration: () => 3,
      enabled: true,
      fetch: () =>
        Promise.reject(new ApiError(422, "REQUEST_INVALID", "bad offset", "rid")),
      page: 2,
      pageSize: 50,
    });
    expect(result).toEqual({
      kind: "error",
      message: "bad offset",
      requestId: "rid",
    });
  });

  it("resolves an async ok page", async () => {
    const result = await loadPagedGeneration({
      started: 4,
      currentGeneration: () => 4,
      enabled: true,
      fetch: async () => pageOf(["n"]),
      page: 1,
      pageSize: 50,
    });
    expect(result).toEqual({ kind: "ok", page: pageOf(["n"]) });
  });
});
