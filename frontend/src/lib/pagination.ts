export type OffsetPage<T> = {
  items: T[];
  total: number;
  limit: number;
  offset: number;
};

export type PageQuery = {
  limit: number;
  offset: number;
};

/** Build an Offset Page envelope from an in-memory collection. */
export function offsetPageFromItems<T>(
  items: readonly T[],
  query: PageQuery,
): OffsetPage<T> {
  const offset = Math.max(0, query.offset);
  const limit = Math.max(0, query.limit);
  return {
    items: items.slice(offset, offset + limit),
    total: items.length,
    limit: query.limit,
    offset: query.offset,
  };
}

/** Largest page index a console list will request. Keeps the offset finite. */
export const MAX_LIST_PAGE = 1_000_000;

/**
 * Page index carried in a query string.
 * Missing, non-integers, and values outside 1..MAX_LIST_PAGE are not pages.
 */
export function acceptedPage(raw: string | null | undefined): number | null {
  const value = Number(raw);
  if (!Number.isSafeInteger(value) || value < 1 || value > MAX_LIST_PAGE) return null;
  return value;
}

/** Member of a closed query set. Anything else is not a value of that set. */
export function acceptedMember(
  value: string | null | undefined,
  members: readonly string[],
): string | null {
  if (value != null && members.includes(value)) return value;
  return null;
}

export function pageToOffset(page: number, pageSize: number): number {
  return Math.max(0, (Math.max(1, page) - 1) * pageSize);
}

export function pageCountOf(total: number, pageSize: number): number {
  if (pageSize <= 0 || total <= 0) return 0;
  return Math.ceil(total / pageSize);
}

export function showingRange(
  total: number,
  page: number,
  pageSize: number,
): { from: number; to: number } {
  if (total <= 0) return { from: 0, to: 0 };
  const from = (Math.max(1, page) - 1) * pageSize + 1;
  return { from, to: Math.min(page * pageSize, total) };
}
