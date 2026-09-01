"use client";

import { Anchor, Breadcrumbs, Text } from "@mantine/core";
import { useBreadcrumb, useTranslate } from "@refinedev/core";
import Link from "next/link";

import { shouldRenderBreadcrumbTrail } from "@/components/layout/breadcrumb-trail";

export function PageBreadcrumb() {
  const t = useTranslate();
  const { breadcrumbs } = useBreadcrumb();

  if (!shouldRenderBreadcrumbTrail(breadcrumbs)) {
    return null;
  }

  return (
    <nav aria-label={t("chrome.breadcrumb")}>
      <Breadcrumbs>
        {breadcrumbs.map((item, index) => {
          const isLast = index === breadcrumbs.length - 1;
          const label = t(item.label);

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
              component={Link}
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
