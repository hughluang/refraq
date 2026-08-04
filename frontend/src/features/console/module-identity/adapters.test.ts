import { describe, expect, it } from "vitest";

import {
  evaluateCan,
  matchPath,
  toRefineResources,
} from "@/features/console/module-identity/adapters";
import { MODULE_IDENTITY_FIXTURE } from "@/features/console/module-identity/fixtures";

describe("toRefineResources", () => {
  it("maps list/create/edit routes and label keys", () => {
    const resources = toRefineResources(MODULE_IDENTITY_FIXTURE);
    expect(resources).toEqual([
      {
        name: "dashboard",
        list: "/console",
        meta: { label: "layout.nav.home" },
      },
      {
        name: "users",
        list: "/console/users",
        create: "/console/users/new",
        meta: { label: "users.title" },
      },
      {
        name: "roles",
        list: "/console/roles",
        create: "/console/roles/new",
        edit: "/console/roles/:id",
        meta: { label: "roles.title" },
      },
      {
        name: "settings",
        list: "/console/settings",
        meta: { label: "settings.title" },
      },
    ]);
  });
});

describe("evaluateCan", () => {
  it("grants list when permission present", () => {
    expect(
      evaluateCan(MODULE_IDENTITY_FIXTURE, ["users:read"], "users", "list"),
    ).toEqual({ can: true });
  });

  it("denies with required permission reason", () => {
    expect(
      evaluateCan(MODULE_IDENTITY_FIXTURE, ["users:read"], "users", "create"),
    ).toEqual({ can: false, reason: "users:write" });
  });

  it("rejects unknown resource and unsupported action", () => {
    expect(evaluateCan(MODULE_IDENTITY_FIXTURE, [], "nope", "list")).toEqual({
      can: false,
      reason: "unknown_resource",
    });
    expect(
      evaluateCan(MODULE_IDENTITY_FIXTURE, ["settings:read"], "settings", "create"),
    ).toEqual({ can: false, reason: "unsupported_action" });
  });
});

describe("matchPath", () => {
  it("matches list create and edit routes", () => {
    expect(matchPath("/console/users", MODULE_IDENTITY_FIXTURE)).toEqual({
      resource: "users",
      action: "list",
    });
    expect(matchPath("/console/users/new", MODULE_IDENTITY_FIXTURE)).toEqual({
      resource: "users",
      action: "create",
    });
    expect(matchPath("/console/roles/abc", MODULE_IDENTITY_FIXTURE)).toEqual({
      resource: "roles",
      action: "edit",
    });
  });

  it("returns null for unregistered paths", () => {
    expect(matchPath("/console/unknown", MODULE_IDENTITY_FIXTURE)).toBeNull();
  });
});
