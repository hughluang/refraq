export const SOURCE_RECORD_TAB = "record";
export const SOURCE_DIFFS_TAB = "diffs";

function withTab(path: string, tab?: string | null): string {
  if (tab && tab !== SOURCE_RECORD_TAB) {
    return `${path}?tab=${encodeURIComponent(tab)}`;
  }
  return path;
}

export function sourceShowPath(sourceId: string, tab?: string | null): string {
  return withTab(`/console/sources/${sourceId}`, tab);
}

export function sourceEditPath(sourceId: string, tab?: string | null): string {
  return withTab(`/console/sources/${sourceId}/edit`, tab);
}

export function sourceDiffsPath(sourceId: string): string {
  return sourceShowPath(sourceId, SOURCE_DIFFS_TAB);
}
