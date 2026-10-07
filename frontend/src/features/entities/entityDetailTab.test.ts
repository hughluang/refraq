import { describe, expect, it } from "vitest";

import {
  createFormErrorTab,
  entityCreateHref,
  entityDetailHref,
  entityEditHref,
  isEntityDetailTab,
  parseEntityDetailTab,
} from "@/features/entities/entityDetailTab";

describe("entityEditHref", () => {
  it("omits the query on overview", () => {
    expect(entityEditHref("ent_1")).toBe("/console/entities/ent_1/edit");
    expect(entityEditHref("ent_1", "overview")).toBe(
      "/console/entities/ent_1/edit",
    );
    expect(entityEditHref("ent_1", "attributes")).toBe(
      "/console/entities/ent_1/edit?tab=attributes",
    );
  });
});

describe("parseEntityDetailTab", () => {
  it("accepts the three tabs and falls back to overview", () => {
    expect(parseEntityDetailTab("overview")).toBe("overview");
    expect(parseEntityDetailTab("attributes")).toBe("attributes");
    expect(parseEntityDetailTab("versions")).toBe("versions");
    expect(parseEntityDetailTab("access")).toBe("access");
    expect(parseEntityDetailTab("data")).toBe("data");
    expect(parseEntityDetailTab(null)).toBe("overview");
    expect(parseEntityDetailTab("nope")).toBe("overview");
  });
});

describe("isEntityDetailTab", () => {
  it("rejects missing and unknown values", () => {
    expect(isEntityDetailTab(null)).toBe(false);
    expect(isEntityDetailTab("nope")).toBe(false);
    expect(isEntityDetailTab("attributes")).toBe(true);
    expect(isEntityDetailTab("access")).toBe(true);
    expect(isEntityDetailTab("data")).toBe(true);
  });
});

describe("entityDetailHref", () => {
  it("omits the query on overview", () => {
    expect(entityDetailHref("ent_1")).toBe("/console/entities/ent_1");
    expect(entityDetailHref("ent_1", "overview")).toBe(
      "/console/entities/ent_1",
    );
    expect(entityDetailHref("ent_1", "attributes")).toBe(
      "/console/entities/ent_1?tab=attributes",
    );
  });
});

describe("entityCreateHref", () => {
  it("omits the query on overview", () => {
    expect(entityCreateHref()).toBe("/console/entities/new");
    expect(entityCreateHref("overview")).toBe("/console/entities/new");
    expect(entityCreateHref("attributes")).toBe(
      "/console/entities/new?tab=attributes",
    );
    expect(entityCreateHref("versions")).toBe(
      "/console/entities/new?tab=versions",
    );
  });
});

describe("createFormErrorTab", () => {
  it("prefers identity errors over attribute errors", () => {
    expect(
      createFormErrorTab({
        table_name: "Required",
        "attributes.0.name": "Required",
      }),
    ).toBe("overview");
  });

  it("selects attributes when only shape fields fail", () => {
    expect(createFormErrorTab({ "attributes.0.name": "Required" })).toBe(
      "attributes",
    );
    expect(createFormErrorTab({ attributes: [{ name: "Required" }] })).toBe(
      "attributes",
    );
  });

  it("falls back to overview when errors are empty", () => {
    expect(createFormErrorTab({})).toBe("overview");
  });
});
