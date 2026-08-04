"use client";

import { Anchor, Breadcrumbs, Text } from "@mantine/core";
import { useBreadcrumb, useTranslate } from "@refinedev/core";
import Link from "next/link";

const MIN_ITEMS = 2;

export function PageBreadcrumb() {
  const t = useTranslate();
  const { breadcrumbs } = useBreadcrumb();

  if (breadcrumbs.length < MIN_ITEMS) {
    return null;
  }

  return (
    <nav aria-label={t("chrome.breadcrumb")}>
      <Breadcrumbs>
        {breadcrumbs.map((item, index) => {
          const isLast = index === breadcrumbs.length - 1;
          // Resource crumbs keep meta.label as i18n keys; action crumbs are already translated.
          const label = item.href ? t(item.label) : item.label;

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
