import { describe, expect, it } from "vitest";

import { shouldRenderBreadcrumbTrail } from "@/components/layout/breadcrumb-trail";

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
