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
