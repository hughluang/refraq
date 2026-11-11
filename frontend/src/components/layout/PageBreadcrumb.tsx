"use client";

import { Anchor, Breadcrumbs, Text } from "@mantine/core";
import { useBreadcrumb, useTranslate } from "@refinedev/core";
import { usePathname } from "next/navigation";

import {
  resolveBreadcrumbTrail,
  shouldRenderBreadcrumbTrail,
} from "@/components/layout/breadcrumb-trail";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { matchPath } from "@/features/console/module-identity/adapters";
import { useModuleIdentityStore } from "@/features/console/module-identity/store";

export function PageBreadcrumb({ currentLabel }: { currentLabel?: string }) {
  const t = useTranslate();
  const { breadcrumbs: refineBreadcrumbs } = useBreadcrumb();
  const pathname = usePathname();
  const modules = useModuleIdentityStore((state) => state.modules);
  const matched = matchPath(pathname, modules);
  const matchedModule = matched
    ? modules.find((item) => item.id === matched.resource)
    : undefined;
  const breadcrumbs = resolveBreadcrumbTrail(
    refineBreadcrumbs,
    matched && matchedModule
      ? {
          action: matched.action,
          labelKey: matchedModule.label_key,
          listHref: matchedModule.routes.list,
        }
      : null,
  );

  if (!shouldRenderBreadcrumbTrail(breadcrumbs)) {
    return null;
  }

  return (
    <nav aria-label={t("layout.breadcrumb")}>
      <Breadcrumbs>
        {breadcrumbs.map((item, index) => {
          const isLast = index === breadcrumbs.length - 1;
          const label = isLast && currentLabel !== undefined ? currentLabel : t(item.label);

          if (isLast || !item.href) {
            return (
              <Text
                key={`${item.label}-${index}`}
                size="sm"
                c="dimmed"
                aria-current={isLast ? "page" : undefined}
              >
                {label}
              </Text>
            );
          }

          return (
            <Anchor
              key={`${item.label}-${index}`}
              component={ConsoleLink}
              href={item.href}
              size="sm"
            >
              {label}
            </Anchor>
          );
        })}
      </Breadcrumbs>
    </nav>
  );
}
