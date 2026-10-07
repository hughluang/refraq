import { classifyAccessProblem, ruleRejectionKey } from "@/features/entities/accessLogic";
import { ApiError } from "@/lib/api";
import { problemMessage } from "@/lib/problem";

type Translate = (key: string, options?: Record<string, unknown>) => string;

export function accessProblemText(err: unknown, t: Translate): string {
  if (err instanceof ApiError) {
    if (err.code === "ENTITY_ACCESS_IN_USE") {
      return t("entities.access.inUse", { detail: err.detail });
    }
    const kind = classifyAccessProblem(err.code);
    if (kind === "pending") return t("entities.access.pending");
    if (kind === "combination_limit") return t("entities.access.overLimit");
    if (err.code === "ENTITY_ACCESS_INVALID") {
      const key = ruleRejectionKey(err.detail);
      if (key) return t(key);
    }
    return problemMessage(t, err, err.detail);
  }
  return String(err);
}
