import type { ChannelRun } from "@/features/channels/types";

type RunSubject = Pick<ChannelRun, "target" | "version">;

/** What a Channel Run executed: a draft, or a published version. */
export function formatRunSubject(
  run: RunSubject,
  t: (key: string, options?: Record<string, unknown>) => string,
): string {
  if (run.target === "draft") {
    return t("channels.runs.subject.draft");
  }
  if (run.version == null) {
    return t("channels.runs.subject.latest");
  }
  return t("channels.runs.subject.version", { number: run.version });
}
