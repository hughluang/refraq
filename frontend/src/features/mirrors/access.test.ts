import { expect, it } from "vitest";
import { evaluateCan, matchAliasPath } from "@/features/console/module-identity/adapters";
import { GENERATED_MODULE_CATALOG } from "@/features/console/module-identity/generated-catalog";

it("gates global metadata and lifecycle writes with distinct mirror permissions", () => {
  expect(evaluateCan(GENERATED_MODULE_CATALOG, ["mirror:read"], "mirrors", "list").can).toBe(true);
  expect(evaluateCan(GENERATED_MODULE_CATALOG, ["mirror:read"], "mirrors", "show").can).toBe(true);
  expect(evaluateCan(GENERATED_MODULE_CATALOG, ["mirror:read"], "mirrors", "edit").can).toBe(false);
  expect(evaluateCan(GENERATED_MODULE_CATALOG, ["sources:data_read"], "mirrors", "list").can).toBe(false);
  expect(evaluateCan(GENERATED_MODULE_CATALOG, ["mirror:write"], "mirrors", "edit").can).toBe(true);
});
it("keeps redacted notification settings under settings read permission", () => {
  expect(matchAliasPath("/console/settings/notification-channel", GENERATED_MODULE_CATALOG)).toEqual({ resource: "settings", action: "list" });
});
