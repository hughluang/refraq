import { describe, expect, it } from "vitest";

import {
  evaluateCan,
  matchPath,
  toRefineResources,
} from "@/features/console/module-identity/adapters";
import { MODULE_IDENTITY_FIXTURE } from "@/features/console/module-identity/fixtures";

describe("toRefineResources", () => {
  it("maps list/create/edit/show routes and label keys", () => {
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
        name: "tokens",
        meta: { label: "tokens.title" },
      },
      {
        name: "sources",
        list: "/console/sources",
        meta: { label: "sources.title" },
      },
      {
        name: "catalog",
        list: "/console/catalog",
        show: "/console/catalog/:id",
        meta: { label: "catalog.title" },
      },
      {
        name: "jobs",
        list: "/console/jobs",
        meta: { label: "jobs.title" },
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

  it("grants catalog show with metadata:read", () => {
    expect(
      evaluateCan(
        MODULE_IDENTITY_FIXTURE,
        ["metadata:read"],
        "catalog",
        "show",
      ),
    ).toEqual({ can: true });
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

  it("does not match removed /console/tokens path", () => {
    expect(matchPath("/console/tokens", MODULE_IDENTITY_FIXTURE)).toBeNull();
  });

  it("matches metadata module routes including catalog show", () => {
    expect(matchPath("/console/sources", MODULE_IDENTITY_FIXTURE)).toEqual({
      resource: "sources",
      action: "list",
    });
    expect(matchPath("/console/catalog", MODULE_IDENTITY_FIXTURE)).toEqual({
      resource: "catalog",
      action: "list",
    });
    expect(matchPath("/console/catalog/obj_1", MODULE_IDENTITY_FIXTURE)).toEqual(
      {
        resource: "catalog",
        action: "show",
      },
    );
    expect(matchPath("/console/jobs", MODULE_IDENTITY_FIXTURE)).toEqual({
      resource: "jobs",
      action: "list",
    });
  });

  it("returns null for unregistered paths", () => {
    expect(matchPath("/console/unknown", MODULE_IDENTITY_FIXTURE)).toBeNull();
  });
});
