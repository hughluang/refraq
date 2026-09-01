export type BreadcrumbTrailItem = {
  label: string;
  href?: string;
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
