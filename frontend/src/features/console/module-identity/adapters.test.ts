import { describe, expect, it } from "vitest";

import {
  evaluateCan,
  isAccessEvaluationPending,
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
        show: "/console/sources/:id/structure-diffs",
        meta: { label: "sources.title" },
      },
      {
        name: "catalog",
        list: "/console/catalog",
        show: "/console/catalog/:id",
        meta: { label: "catalog.title" },
      },
      {
        name: "business-domains",
        list: "/console/business-domains",
        create: "/console/business-domains",
        edit: "/console/business-domains",
        meta: { label: "businessDomains.title" },
      },
      {
        name: "type-mappings",
        list: "/console/type-mappings",
        edit: "/console/type-mappings",
        meta: { label: "typeMappings.title" },
      },
      {
        name: "jobs",
        list: "/console/jobs",
        meta: { label: "jobs.title" },
      },
      {
        name: "schedules",
        list: "/console/schedules",
        edit: "/console/schedules",
        meta: { label: "schedules.title" },
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

  it("grants sources show with metadata:read", () => {
    expect(
      evaluateCan(
        MODULE_IDENTITY_FIXTURE,
        ["metadata:read"],
        "sources",
        "show",
      ),
    ).toEqual({ can: true });
  });

  it("grants catalog sample with catalog:sample", () => {
    expect(
      evaluateCan(
        MODULE_IDENTITY_FIXTURE,
        ["catalog:sample"],
        "catalog",
        "sample",
      ),
    ).toEqual({ can: true });
  });

  it("denies catalog sample when only metadata:write is present", () => {
    expect(
      evaluateCan(
        MODULE_IDENTITY_FIXTURE,
        ["metadata:write"],
        "catalog",
        "sample",
      ),
    ).toEqual({ can: false, reason: "catalog:sample" });
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

describe("isAccessEvaluationPending", () => {
  it("treats loading and undefined data as pending", () => {
    expect(isAccessEvaluationPending(true, { can: false })).toBe(true);
    expect(isAccessEvaluationPending(false, undefined)).toBe(true);
  });

  it("treats identity and permission bootstrap reasons as pending", () => {
    expect(
      isAccessEvaluationPending(false, {
        can: false,
        reason: "module_identity_not_ready",
      }),
    ).toBe(true);
    expect(
      isAccessEvaluationPending(false, {
        can: false,
        reason: "user_permissions_not_ready",
      }),
    ).toBe(true);
  });

  it("does not treat a resolved catalog:sample deny as pending", () => {
    expect(
      isAccessEvaluationPending(false, {
        can: false,
        reason: "catalog:sample",
      }),
    ).toBe(false);
    expect(isAccessEvaluationPending(false, { can: true })).toBe(false);
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
    expect(matchPath("/console/schedules", MODULE_IDENTITY_FIXTURE)).toEqual({
      resource: "schedules",
      action: "list",
    });
    expect(
      matchPath("/console/sources/src_1/structure-diffs", MODULE_IDENTITY_FIXTURE),
    ).toEqual({
      resource: "sources",
      action: "show",
    });
    expect(
      matchPath(
        "/console/sources/src_1/structure-diffs/sdiff_1",
        MODULE_IDENTITY_FIXTURE,
      ),
    ).toBeNull();
    expect(
      matchPath("/console/sources/src_1/schedules", MODULE_IDENTITY_FIXTURE),
    ).toBeNull();
  });

  it("returns null for unregistered paths", () => {
    expect(matchPath("/console/unknown", MODULE_IDENTITY_FIXTURE)).toBeNull();
  });
});
