import { describe, expect, it } from "vitest";

import {
  evaluateCan,
  isAccessEvaluationPending,
  matchPath,
  toRefineResources,
} from "@/features/console/module-identity/adapters";
import { GENERATED_MODULE_CATALOG } from "@/features/console/module-identity/generated-catalog";

const CATALOG = GENERATED_MODULE_CATALOG;

describe("toRefineResources", () => {
  it("maps list/create/edit/show routes and label keys", () => {
    const resources = toRefineResources(CATALOG);
    expect(resources.find((item) => item.name === "schedules")).toEqual({
      name: "schedules",
      list: "/console/schedules",
      edit: "/console/schedules",
      show: "/console/sources/:id/schedules",
      meta: { label: "schedules.title" },
    });
    expect(resources.find((item) => item.name === "account")).toEqual({
      name: "account",
      show: "/console/account",
      meta: { label: "account.title" },
    });
    expect(resources.find((item) => item.name === "sources")).toEqual({
      name: "sources",
      list: "/console/sources",
      show: "/console/sources/:id/structure-diffs",
      meta: { label: "sources.title" },
    });
  });
});

describe("evaluateCan", () => {
  it("grants list when permission present", () => {
    expect(evaluateCan(CATALOG, ["users:read"], "users", "list")).toEqual({
      can: true,
    });
  });

  it("denies with required permission reason", () => {
    expect(evaluateCan(CATALOG, ["users:read"], "users", "create")).toEqual({
      can: false,
      reason: "users:write",
    });
  });

  it("grants catalog show with metadata:read", () => {
    expect(
      evaluateCan(CATALOG, ["metadata:read"], "catalog", "show"),
    ).toEqual({ can: true });
  });

  it("grants sources show with metadata:read", () => {
    expect(
      evaluateCan(CATALOG, ["metadata:read"], "sources", "show"),
    ).toEqual({ can: true });
  });

  it("grants schedules show with jobs:run", () => {
    expect(
      evaluateCan(CATALOG, ["jobs:run"], "schedules", "show"),
    ).toEqual({ can: true });
  });

  it("grants account show with console:access", () => {
    expect(
      evaluateCan(CATALOG, ["console:access"], "account", "show"),
    ).toEqual({ can: true });
  });

  it("grants catalog sample with catalog:sample", () => {
    expect(
      evaluateCan(CATALOG, ["catalog:sample"], "catalog", "sample"),
    ).toEqual({ can: true });
  });

  it("denies catalog sample when only metadata:write is present", () => {
    expect(
      evaluateCan(CATALOG, ["metadata:write"], "catalog", "sample"),
    ).toEqual({ can: false, reason: "catalog:sample" });
  });

  it("rejects unknown resource and unsupported action", () => {
    expect(evaluateCan(CATALOG, [], "nope", "list")).toEqual({
      can: false,
      reason: "unknown_resource",
    });
    expect(
      evaluateCan(CATALOG, ["settings:read"], "settings", "create"),
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
    expect(matchPath("/console/users", CATALOG)).toEqual({
      resource: "users",
      action: "list",
    });
    expect(matchPath("/console/users/new", CATALOG)).toEqual({
      resource: "users",
      action: "create",
    });
    expect(matchPath("/console/roles/abc", CATALOG)).toEqual({
      resource: "roles",
      action: "edit",
    });
  });

  it("does not match removed /console/tokens path", () => {
    expect(matchPath("/console/tokens", CATALOG)).toBeNull();
  });

  it("matches metadata module routes including catalog show", () => {
    expect(matchPath("/console/sources", CATALOG)).toEqual({
      resource: "sources",
      action: "list",
    });
    expect(matchPath("/console/catalog", CATALOG)).toEqual({
      resource: "catalog",
      action: "list",
    });
    expect(matchPath("/console/catalog/obj_1", CATALOG)).toEqual({
      resource: "catalog",
      action: "show",
    });
    expect(matchPath("/console/jobs", CATALOG)).toEqual({
      resource: "jobs",
      action: "list",
    });
    expect(matchPath("/console/schedules", CATALOG)).toEqual({
      resource: "schedules",
      action: "list",
    });
    expect(
      matchPath("/console/sources/src_1/structure-diffs", CATALOG),
    ).toEqual({
      resource: "sources",
      action: "show",
    });
  });

  it("matches alias and primary show routes for source subpages", () => {
    expect(
      matchPath(
        "/console/sources/src_1/structure-diffs/sdiff_1",
        CATALOG,
      ),
    ).toEqual({
      resource: "sources",
      action: "show",
    });
    expect(matchPath("/console/sources/src_1/schedules", CATALOG)).toEqual({
      resource: "schedules",
      action: "show",
    });
    expect(matchPath("/console/account", CATALOG)).toEqual({
      resource: "account",
      action: "show",
    });
  });

  it("returns null for unregistered paths", () => {
    expect(matchPath("/console/unknown", CATALOG)).toBeNull();
    expect(matchPath("/console/sources/src_1/not-a-page", CATALOG)).toBeNull();
  });
});
