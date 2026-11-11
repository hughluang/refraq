import { describe, expect, it } from "vitest";

import {
  resolveBreadcrumbTrail,
  shouldRenderBreadcrumbTrail,
} from "@/components/layout/breadcrumb-trail";

describe("shouldRenderBreadcrumbTrail", () => {
  it("hides an identity-only show trail with no list href", () => {
    expect(
      shouldRenderBreadcrumbTrail([
        { label: "account.title" },
        { label: "Show" },
      ]),
    ).toBe(false);
  });

  it("hides a single list crumb", () => {
    expect(
      shouldRenderBreadcrumbTrail([
        { label: "users.title", href: "/console/users" },
      ]),
    ).toBe(false);
  });

  it("shows a list-backed create trail", () => {
    expect(
      shouldRenderBreadcrumbTrail([
        { label: "users.title", href: "/console/users" },
        { label: "Create" },
      ]),
    ).toBe(true);
  });
});

describe("resolveBreadcrumbTrail", () => {
  const aliasShow = {
    action: "show",
    labelKey: "mcp.title",
    listHref: "/console/mcp",
  };

  it("keeps a Refine trail that already navigates", () => {
    const refine = [
      { label: "from-refine", href: "/console/mcp" },
      { label: "refine-current" },
    ];
    expect(resolveBreadcrumbTrail(refine, aliasShow)).toEqual(refine);
  });

  it("synthesizes a list link and a non-link action for an alias show", () => {
    expect(resolveBreadcrumbTrail([], aliasShow)).toEqual([
      { label: "mcp.title", href: "/console/mcp" },
      { label: "actions.show" },
    ]);
  });

  it("does not synthesize a list page or a module without a list route", () => {
    expect(
      resolveBreadcrumbTrail([], { ...aliasShow, action: "list" }),
    ).toEqual([]);
    expect(
      resolveBreadcrumbTrail([], { ...aliasShow, listHref: null }),
    ).toEqual([]);
    expect(resolveBreadcrumbTrail([], null)).toEqual([]);
  });
});
