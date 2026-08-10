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
    routes: { list: "/console/sources", create: null, edit: null },
    actions: {
      list: "sources:read",
      create: "sources:write",
      edit: "sources:write",
      delete: "sources:write",
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
