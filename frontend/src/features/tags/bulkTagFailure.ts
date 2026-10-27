import { ApiError } from "@/lib/api";
import { listErrorMessage } from "@/lib/paged-list-session";
import { problemMessage } from "@/lib/problem";

type Translate = (key: string, values?: Record<string, string>) => string;

/**
 * A bulk Tag add or remove that returns a Problem wrote nothing.
 * `subjects` are ids this page sent. The page map has each display name.
 */
export function bulkTagFailureMessage(
  t: Translate,
  error: unknown,
  namesById: ReadonlyMap<string, string>,
): string {
  if (!(error instanceof ApiError)) return listErrorMessage(error);
  const lead = problemMessage(t, error, t("problems.unknown"));
  const unchanged = t("tags.bulk.wroteNothing");
  const labels = subjectLabels(error.extensions.subjects, namesById);
  if (labels.length === 0) return t("tags.bulk.refused", { lead, unchanged });
  return t("tags.bulk.refusedNamed", {
    lead,
    names: labels.join(t("tags.bulk.nameSeparator")),
    unchanged,
  });
}

function subjectLabels(subjects: unknown, namesById: ReadonlyMap<string, string>): string[] {
  if (!Array.isArray(subjects)) return [];
  return subjects.map((item) => namesById.get((item as { id: string }).id)!);
}
