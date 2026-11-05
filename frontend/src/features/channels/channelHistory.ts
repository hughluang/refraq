import { acceptedMember, acceptedPage } from "@/lib/pagination";

export const RUN_STATUS_VALUES = ["queued", "running", "succeeded", "failed", "cancelled"] as const;
export const RUN_TARGET_VALUES = ["draft", "published"] as const;

export function historyContext(search: string): string {
  const source = new URLSearchParams(search);
  const result = new URLSearchParams({ run_panel: "runs" });
  if (source.get("run_origin") === "edit") result.set("run_origin", "edit");
  const status = acceptedMember(source.get("run_status"), RUN_STATUS_VALUES);
  if (status) result.set("run_status", status);
  const target = acceptedMember(source.get("run_target"), RUN_TARGET_VALUES);
  if (target) result.set("run_target", target);
  const page = acceptedPage(source.get("run_page"));
  if (page != null && page > 1) result.set("run_page", String(page));
  return result.toString();
}

export function historyReturn(channelId: string, search: string): string {
  const context = historyContext(search);
  const edit = new URLSearchParams(context).get("run_origin") === "edit";
  return `/console/channels/${encodeURIComponent(channelId)}${edit ? "/edit" : ""}?${context}`;
}
