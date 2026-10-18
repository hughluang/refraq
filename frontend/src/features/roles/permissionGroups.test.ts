import { describe, expect, it } from "vitest";

import { groupPermissions, permissionGroupId } from "@/features/roles/permissionGroups";
import type { ModuleIdentity } from "@/features/console/module-identity/types";
import type { PermissionCatalogEntry } from "@/features/roles/types";

const modules: ModuleIdentity[] = [
  {
    id: "users",
    label_key: "users.title",
    routes: { list: "/console/users" },
    actions: { list: "users:read", create: "users:write" },
  },
  {
    id: "roles",
    label_key: "roles.title",
    routes: { list: "/console/roles" },
    actions: { list: "roles:read" },
  },
];

describe("permission groups", () => {
  it("groups a key by its module prefix", () => {
    expect(permissionGroupId("users:write", modules)).toBe("users");
    expect(permissionGroupId("roles:read", modules)).toBe("roles");
  });

  it("keeps an unknown prefix as its own group", () => {
    expect(permissionGroupId("custom:read", modules)).toBe("custom");
  });

  it("orders groups by first appearance and labels known modules", () => {
    const entries: PermissionCatalogEntry[] = [
      { key: "roles:read", description: "Read roles" },
      { key: "users:read", description: "Read users" },
      { key: "users:write", description: "Write users" },
    ];
    const groups = groupPermissions(entries, modules);
    expect(groups.map((group) => group.id)).toEqual(["roles", "users"]);
    expect(groups[1]?.labelKey).toBe("users.title");
    expect(groups[1]?.entries.map((entry) => entry.key)).toEqual([
      "users:read",
      "users:write",
    ]);
  });
});
