export type BreadcrumbTrailItem = {
  label: string;
  href?: string;
};

export type AliasBreadcrumbSource = {
  action: string;
  labelKey: string;
  listHref: string | null;
};

const MIN_ITEMS = 2;

/**
 * A trail is a navigation path: at least two items and a list-route ancestor.
 * Identity-only pages (no list href) and single-crumb list pages stay hidden.
 */
export function shouldRenderBreadcrumbTrail(
  items: ReadonlyArray<BreadcrumbTrailItem>,
): boolean {
  return (
    items.length >= MIN_ITEMS && items.some((item) => Boolean(item.href))
  );
}

/**
 * Prefer a Refine trail that already navigates. An alias show, edit, or create
 * whose module has a list route gets that same two-segment shape when Refine
 * did not match the path.
 */
export function resolveBreadcrumbTrail(
  refineBreadcrumbs: ReadonlyArray<BreadcrumbTrailItem>,
  aliasSource: AliasBreadcrumbSource | null,
): BreadcrumbTrailItem[] {
  if (shouldRenderBreadcrumbTrail(refineBreadcrumbs)) {
    return [...refineBreadcrumbs];
  }
  if (aliasSource && aliasSource.action !== "list" && aliasSource.listHref) {
    return [
      { label: aliasSource.labelKey, href: aliasSource.listHref },
      { label: `actions.${aliasSource.action}` },
    ];
  }
  return [];
}
