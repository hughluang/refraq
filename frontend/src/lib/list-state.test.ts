import { describe, expect, it } from "vitest";

import {
  isRefreshing,
  listPresentationOf,
  listStateOf,
} from "@/lib/list-state";

const base = {
  loading: false,
  error: null as string | null,
  total: 0,
  itemCount: 0,
  filtered: false,
};

describe("listStateOf", () => {
  it("shows loading when a fetch has no rows yet", () => {
    expect(listStateOf({ ...base, loading: true })).toBe("loading");
    expect(
      listStateOf({
        ...base,
        loading: true,
        error: "stale",
        total: 0,
        filtered: true,
      }),
    ).toBe("loading");
  });

  it("keeps rows on screen while a later page loads", () => {
    expect(
      listStateOf({
        ...base,
        loading: true,
        total: 120,
        itemCount: 100,
      }),
    ).toBe("ready");
  });

  it("shows error only when there are no rows to keep", () => {
    expect(listStateOf({ ...base, error: "failed to load" })).toBe("error");
    expect(
      listStateOf({
        ...base,
        error: "failed to load",
        total: 12,
        itemCount: 12,
      }),
    ).toBe("ready");
  });

  it("gates empty on total, not itemCount", () => {
    expect(listStateOf(base)).toBe("empty");
    expect(listStateOf({ ...base, total: 120, itemCount: 0 })).toBe("ready");
  });

  it("splits a vacant collection from a vacant filter result", () => {
    expect(listStateOf({ ...base, filtered: true })).toBe("no-match");
    expect(
      listStateOf({ ...base, filtered: true, total: 8, itemCount: 8 }),
    ).toBe("ready");
  });
});

describe("isRefreshing", () => {
  it("is true only while loading over existing rows", () => {
    expect(isRefreshing({ loading: false, itemCount: 10 })).toBe(false);
    expect(isRefreshing({ loading: true, itemCount: 0 })).toBe(false);
    expect(isRefreshing({ loading: true, itemCount: 10 })).toBe(true);
  });
});

describe("listPresentationOf", () => {
  it("pairs initial load with no refresh dim", () => {
    expect(listPresentationOf({ ...base, loading: true })).toEqual({
      state: "loading",
      refreshing: false,
    });
  });

  it("dims stale rows while a later fetch runs", () => {
    expect(
      listPresentationOf({
        ...base,
        loading: true,
        total: 120,
        itemCount: 100,
      }),
    ).toEqual({ state: "ready", refreshing: true });
  });

  it("keeps stale rows after a later fetch fails", () => {
    expect(
      listPresentationOf({
        ...base,
        error: "failed to load",
        total: 12,
        itemCount: 12,
      }),
    ).toEqual({ state: "ready", refreshing: false });
  });

  it("treats a vacant filter result as no-match, not empty", () => {
    expect(listPresentationOf({ ...base, filtered: true })).toEqual({
      state: "no-match",
      refreshing: false,
    });
  });

  it("treats a past-end page as ready, not empty", () => {
    expect(
      listPresentationOf({ ...base, total: 120, itemCount: 0 }),
    ).toEqual({ state: "ready", refreshing: false });
  });
});
