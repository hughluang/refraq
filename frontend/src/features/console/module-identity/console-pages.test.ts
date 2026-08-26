import { readdirSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { GENERATED_MODULE_CATALOG } from "@/features/console/module-identity/generated-catalog";
import type { ModuleIdentity } from "@/features/console/module-identity/types";

const CONSOLE_APP_DIR = path.resolve(
  import.meta.dirname,
  "../../../app/console",
);

const CATCH_ALL_SEGMENT = "[...slug]";

function collectCatalogRoutePaths(modules: ModuleIdentity[]): Set<string> {
  const paths = new Set<string>();
  for (const module of modules) {
    const { list, create, edit, show, aliases } = module.routes;
    for (const route of [list, create, edit, show]) {
      if (route) {
        paths.add(route);
      }
    }
    for (const alias of aliases ?? []) {
      paths.add(alias.path);
    }
  }
  return paths;
}

function pageFileToRoute(relativePagePath: string): string {
  const withoutPage = relativePagePath.replace(/\/page\.tsx$/, "");
  if (withoutPage === "" || withoutPage === "page.tsx") {
    return "/console";
  }
  const segments = withoutPage.split("/").map((segment) => {
    if (segment.startsWith("[") && segment.endsWith("]")) {
      return `:${segment.slice(1, -1)}`;
    }
    return segment;
  });
  return `/console/${segments.join("/")}`;
}

function collectConsolePageRoutes(dir: string, prefix = ""): Set<string> {
  const routes = new Set<string>();
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (entry.name === CATCH_ALL_SEGMENT) {
      continue;
    }
    const relative = prefix ? `${prefix}/${entry.name}` : entry.name;
    const absolute = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      for (const route of collectConsolePageRoutes(absolute, relative)) {
        routes.add(route);
      }
      continue;
    }
    if (entry.name === "page.tsx") {
      routes.add(pageFileToRoute(relative));
    }
  }
  return routes;
}

describe("console module catalog routes vs page.tsx", () => {
  it("matches every catalog route to exactly one console page and vice versa", () => {
    const catalogRoutes = collectCatalogRoutePaths(GENERATED_MODULE_CATALOG);
    const pageRoutes = collectConsolePageRoutes(CONSOLE_APP_DIR);

    const onlyInCatalog = [...catalogRoutes].filter(
      (route) => !pageRoutes.has(route),
    );
    const onlyInPages = [...pageRoutes].filter(
      (route) => !catalogRoutes.has(route),
    );

    expect(
      { onlyInCatalog, onlyInPages },
      "catalog routes and console page.tsx files must be in bijection",
    ).toEqual({ onlyInCatalog: [], onlyInPages: [] });
  });
});
