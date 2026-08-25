import { describe, expect, it } from "vitest";

import {
  offsetPageFromItems,
  pageCountOf,
  pageToOffset,
  showingRange,
} from "@/lib/pagination";

describe("pageToOffset", () => {
  it("maps 1-based pages", () => {
    expect(pageToOffset(1, 50)).toBe(0);
    expect(pageToOffset(2, 50)).toBe(50);
    expect(pageToOffset(3, 20)).toBe(40);
  });

  it("clamps page below 1 to the first page", () => {
    expect(pageToOffset(0, 50)).toBe(0);
    expect(pageToOffset(-2, 50)).toBe(0);
  });
});

describe("pageCountOf", () => {
  it("returns 0 for empty or invalid sizes", () => {
    expect(pageCountOf(0, 50)).toBe(0);
    expect(pageCountOf(10, 0)).toBe(0);
  });

  it("rounds up a partial last page", () => {
    expect(pageCountOf(50, 50)).toBe(1);
    expect(pageCountOf(51, 50)).toBe(2);
  });
});

describe("showingRange", () => {
  it("returns zeros when the set is empty", () => {
    expect(showingRange(0, 1, 50)).toEqual({ from: 0, to: 0 });
  });

  it("covers a middle and last page", () => {
    expect(showingRange(120, 1, 50)).toEqual({ from: 1, to: 50 });
    expect(showingRange(120, 3, 50)).toEqual({ from: 101, to: 120 });
  });

  it("covers a short first page for the count text", () => {
    expect(showingRange(12, 1, 50)).toEqual({ from: 1, to: 12 });
  });
});

describe("offsetPageFromItems", () => {
  it("slices the in-memory collection and echoes the query", () => {
    expect(offsetPageFromItems(["a", "b", "c", "d"], { limit: 2, offset: 2 })).toEqual({
      items: ["c", "d"],
      total: 4,
      limit: 2,
      offset: 2,
    });
  });

  it("returns an empty page when offset is past the end", () => {
    expect(offsetPageFromItems(["a"], { limit: 50, offset: 50 })).toEqual({
      items: [],
      total: 1,
      limit: 50,
      offset: 50,
    });
  });
});
