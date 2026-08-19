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
 * `usePagedList` `onError` or the Refine list notification still toasts).
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
