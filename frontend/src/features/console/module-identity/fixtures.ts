import type { ModuleIdentity } from "@/features/console/module-identity/types";

/** Mirrors backend seed / GET /console/module-identities contract for adapter tests. */
export const MODULE_IDENTITY_FIXTURE: ModuleIdentity[] = [
  {
    id: "dashboard",
    label_key: "layout.nav.home",
    routes: { list: "/console", create: null, edit: null },
    actions: {
      list: "dashboard:read",
      create: null,
      edit: null,
      delete: null,
    },
  },
  {
    id: "users",
    label_key: "users.title",
    routes: {
      list: "/console/users",
      create: "/console/users/new",
      edit: null,
    },
    actions: {
      list: "users:read",
      create: "users:write",
      edit: "users:write",
      delete: "users:write",
    },
  },
  {
    id: "identity-providers",
    label_key: "identityProviders.title",
    routes: {
      list: "/console/identity-providers",
      create: null,
      edit: null,
    },
    actions: {
      list: "identity_providers:read",
      create: "identity_providers:write",
      edit: "identity_providers:write",
      delete: "identity_providers:write",
    },
  },
  {
    id: "roles",
    label_key: "roles.title",
    routes: {
      list: "/console/roles",
      create: "/console/roles/new",
      edit: "/console/roles/:id",
    },
    actions: {
      list: "roles:read",
      create: "roles:write",
      edit: "roles:write",
      delete: "roles:write",
    },
  },
  {
    id: "tokens",
    label_key: "tokens.title",
    routes: { list: null, create: null, edit: null },
    actions: {
      list: "tokens:read",
      create: "tokens:write",
      edit: "tokens:write",
      delete: "tokens:write",
    },
  },
  {
    id: "sources",
    label_key: "sources.title",
    routes: {
      list: "/console/sources",
      create: null,
      edit: null,
      show: "/console/sources/:id/structure-diffs",
    },
    actions: {
      list: "sources:read",
      create: "sources:write",
      edit: "sources:write",
      delete: "sources:write",
      show: "metadata:read",
    },
  },
  {
    id: "catalog",
    label_key: "catalog.title",
    routes: {
      list: "/console/catalog",
      create: null,
      edit: null,
      show: "/console/catalog/:id",
    },
    actions: {
      list: "metadata:read",
      create: null,
      edit: "metadata:write",
      delete: null,
      show: "metadata:read",
      sample: "catalog:sample",
    },
  },
  {
    id: "business-domains",
    label_key: "businessDomains.title",
    routes: {
      list: "/console/business-domains",
      create: "/console/business-domains",
      edit: "/console/business-domains",
    },
    actions: {
      list: "metadata:read",
      create: "metadata:write",
      edit: "metadata:write",
      delete: "metadata:write",
    },
  },
  {
    id: "type-mappings",
    label_key: "typeMappings.title",
    routes: {
      list: "/console/type-mappings",
      create: null,
      edit: "/console/type-mappings",
    },
    actions: {
      list: "metadata:read",
      create: null,
      edit: "metadata:write",
      delete: null,
    },
  },
  {
    id: "jobs",
    label_key: "jobs.title",
    routes: { list: "/console/jobs", create: null, edit: null },
    actions: {
      list: "jobs:run",
      create: null,
      edit: null,
      delete: null,
    },
  },
  {
    id: "schedules",
    label_key: "schedules.title",
    routes: { list: "/console/schedules", create: null, edit: "/console/schedules" },
    actions: {
      list: "jobs:run",
      create: null,
      edit: "jobs:run",
      delete: "jobs:run",
    },
  },
  {
    id: "settings",
    label_key: "settings.title",
    routes: { list: "/console/settings", create: null, edit: null },
    actions: {
      list: "settings:read",
      create: null,
      edit: "settings:write",
      delete: null,
    },
  },
];
