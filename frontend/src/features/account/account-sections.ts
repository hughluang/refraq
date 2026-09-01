export const ACCOUNT_SECTION = {
  profile: "account-profile",
  tokens: "account-tokens",
  mcp: "account-mcp",
} as const;

export type AccountSectionObservation = {
  id: string;
  intersectionRatio: number;
  top: number;
};

export function scrollAccountSection(id: string): void {
  document.getElementById(id)?.scrollIntoView({
    behavior: "smooth",
    block: "start",
  });
}

export function accountPageScrollRoot(
  from: HTMLElement | null,
): Element | null {
  let node = from?.parentElement ?? null;
  while (node) {
    const { overflowY } = getComputedStyle(node);
    if (overflowY === "auto" || overflowY === "scroll") {
      return node;
    }
    node = node.parentElement;
  }
  return null;
}

/** Current section from latest observer snapshots. `top` is relative to the scroll root. */
export function activeAccountSection(
  observations: ReadonlyArray<AccountSectionObservation>,
): string | null {
  if (observations.length === 0) {
    return null;
  }
  const visible = observations.filter((item) => item.intersectionRatio > 0);
  const pool = visible.length > 0 ? visible : observations;
  const crossing = pool.filter((item) => item.top <= 0);
  if (crossing.length > 0) {
    return crossing.reduce((best, item) =>
      item.top > best.top ? item : best,
    ).id;
  }
  return pool.reduce((best, item) => (item.top < best.top ? item : best)).id;
}

export function observationFromEntry(
  entry: IntersectionObserverEntry,
): AccountSectionObservation | null {
  const id = entry.target.id;
  if (!id) {
    return null;
  }
  const rootTop = entry.rootBounds?.top ?? 0;
  return {
    id,
    intersectionRatio: entry.intersectionRatio,
    top: entry.boundingClientRect.top - rootTop,
  };
}
