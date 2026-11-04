export function historyContext(search: string): string {
  const source = new URLSearchParams(search);
  const result = new URLSearchParams({ run_panel: "runs" });
  if (source.get("run_origin") === "edit") result.set("run_origin", "edit");
  const status = source.get("run_status");
  if (status && ["queued", "running", "succeeded", "failed", "cancelled"].includes(status)) result.set("run_status", status);
  const target = source.get("run_target");
  if (target === "draft" || target === "published") result.set("run_target", target);
  const page = Number(source.get("run_page"));
  if (Number.isSafeInteger(page) && page > 1 && page <= 1000000) result.set("run_page", String(page));
  return result.toString();
}

export function historyReturn(channelId: string, search: string): string {
  const context = historyContext(search);
  const edit = new URLSearchParams(context).get("run_origin") === "edit";
  return `/console/channels/${encodeURIComponent(channelId)}${edit ? "/edit" : ""}?${context}`;
}
