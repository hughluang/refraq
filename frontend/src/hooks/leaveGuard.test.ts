import { describe, expect, it } from "vitest";

import { isLeaveHref } from "@/hooks/leaveGuard";

describe("isLeaveHref", () => {
  it("treats query-only changes as staying on the page", () => {
    expect(
      isLeaveHref(
        "http://localhost/console/entities/ent_1?tab=attributes",
        "/console/entities/ent_1?tab=versions",
      ),
    ).toBe(false);
    expect(
      isLeaveHref(
        "http://localhost/console/entities/ent_1?tab=attributes",
        "/console/entities/ent_1",
      ),
    ).toBe(false);
  });

  it("treats identity edit as leaving the detail page", () => {
    expect(
      isLeaveHref(
        "http://localhost/console/entities/ent_1?tab=attributes",
        "/console/entities/ent_1/edit",
      ),
    ).toBe(true);
  });

  it("treats query-only changes on edit as staying", () => {
    expect(
      isLeaveHref(
        "http://localhost/console/entities/ent_1/edit?tab=attributes",
        "/console/entities/ent_1/edit?tab=versions",
      ),
    ).toBe(false);
  });

  it("treats the list as leaving create and detail", () => {
    expect(
      isLeaveHref(
        "http://localhost/console/entities/new",
        "/console/entities",
      ),
    ).toBe(true);
    expect(
      isLeaveHref(
        "http://localhost/console/entities/ent_1",
        "/console/entities",
      ),
    ).toBe(true);
  });
});
