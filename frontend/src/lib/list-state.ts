export type ListState = "loading" | "error" | "empty" | "no-match" | "ready";

export type ListStateInput = {
  loading: boolean;
  error: string | null;
  total: number;
  itemCount: number;
  filtered: boolean;
};

export type ListPresentation = {
  state: ListState;
  refreshing: boolean;
};

/**
 * Decide which status a paged list should render.
 *
 * Error only wins when there are no rows (rows present stay on screen;
 * a later failure toasts only if the caller passed `usePagedList` `onError`).
 * The empty gate reads `total`, not `itemCount`, so a past-end page is not
 * an empty list. `filtered` splits a vacant collection from a vacant filter
 * result.
 */
export function listStateOf(input: ListStateInput): ListState {
  const { loading, error, total, itemCount, filtered } = input;
  if (loading && itemCount === 0) return "loading";
  if (error && itemCount === 0) return "error";
  if (total === 0) return filtered ? "no-match" : "empty";
  return "ready";
}

export function isRefreshing(input: {
  loading: boolean;
  itemCount: number;
}): boolean {
  return input.loading && input.itemCount > 0;
}

/** Pair list status with the in-place refresh dim for one table render. */
export function listPresentationOf(input: ListStateInput): ListPresentation {
  return {
    state: listStateOf(input),
    refreshing: isRefreshing(input),
  };
}

/** Fields a `ListTable` binds for a collection that is not an Offset Page fetch. */
export type LocalListSession = {
  presentation: ListPresentation;
  error: string | null;
  errorRequestId: string | null;
  reload: () => void | Promise<void>;
  page: number;
  setPage: (page: number) => void;
  pageSize: number;
  total: number;
};

function ignorePage(_page: number) {}

/**
 * One in-memory collection as a list session.
 * All rows sit on a single page, so the pager shows the count and no page numbers.
 */
export function localListSession(input: {
  total: number;
  loading?: boolean;
  error?: string | null;
  reload?: () => void | Promise<void>;
}): LocalListSession {
  const error = input.error ?? null;
  const loading = input.loading ?? false;
  const itemCount = loading || error ? 0 : input.total;
  return {
    presentation: listPresentationOf({
      loading,
      error,
      total: input.total,
      itemCount,
      filtered: false,
    }),
    error,
    errorRequestId: null,
    reload: input.reload ?? (() => undefined),
    page: 1,
    setPage: ignorePage,
    pageSize: Math.max(input.total, 1),
    total: input.total,
  };
}
