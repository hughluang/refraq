/** Floors for the run-detail workspace, in rem. 64 = 16 + 20 + 28. 48 = 20 + 28. */
export const RUN_DETAIL_INDEX_MIN_REM = 16;
export const RUN_DETAIL_GRAPH_MIN_REM = 20;
export const RUN_DETAIL_INSPECTOR_MIN_REM = 28;
export const RUN_DETAIL_COLUMNS_MIN_REM =
  RUN_DETAIL_INDEX_MIN_REM + RUN_DETAIL_GRAPH_MIN_REM + RUN_DETAIL_INSPECTOR_MIN_REM;
export const RUN_DETAIL_BAND_MIN_REM = RUN_DETAIL_GRAPH_MIN_REM + RUN_DETAIL_INSPECTOR_MIN_REM;

export type RunDetailArrangement = "columns" | "band" | "stack";

/**
 * Choose how the execution index, the graph, and the inspector share the
 * workspace. `widthPx` is the workspace's own width, not the viewport.
 * A non-positive root font falls back to 16px.
 */
export function runDetailArrangement(widthPx: number, rootFontPx: number): RunDetailArrangement {
  const rem = rootFontPx > 0 ? rootFontPx : 16;
  const widthRem = widthPx / rem;
  if (widthRem >= RUN_DETAIL_COLUMNS_MIN_REM) return "columns";
  if (widthRem >= RUN_DETAIL_BAND_MIN_REM) return "band";
  return "stack";
}
