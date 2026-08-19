import { describe, expect, it } from "vitest";

import {
  catalogPresence,
  catalogSemanticsReady,
} from "@/features/sources/catalog-detail/catalogStatus";

describe("catalogPresence", () => {
  it("maps present and absent", () => {
    expect(catalogPresence(true)).toEqual({
      labelKey: "catalog.fields.presentValue",
      color: "green",
    });
    expect(catalogPresence(false)).toEqual({
      labelKey: "catalog.fields.absentValue",
      color: "gray",
    });
  });
});

describe("catalogSemanticsReady", () => {
  it("maps ready and not ready", () => {
    expect(catalogSemanticsReady(true)).toEqual({
      labelKey: "catalog.semantics.ready",
      color: "green",
    });
    expect(catalogSemanticsReady(false)).toEqual({
      labelKey: "catalog.semantics.notReady",
      color: "gray",
    });
  });
});
