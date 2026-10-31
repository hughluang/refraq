import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import type { ApplyApiErrorResult } from "@/components/form/useConsoleForm";
import { ApiError } from "@/lib/api";

type Translate = (key: string) => string;

function fieldsHoldEveryDetail(error: unknown, result: ApplyApiErrorResult): boolean {
  return (
    error instanceof ApiError &&
    error.status === 422 &&
    result.mapped.length > 0 &&
    result.unmapped.length === 0
  );
}

/** Mark whatever the form can mark. Notify once unless every 422 detail landed on a field. */
export function presentSaveFailure(
  t: Translate,
  error: unknown,
  applyApiError: (error: unknown) => ApplyApiErrorResult,
): void {
  const result = applyApiError(error);
  if (fieldsHoldEveryDetail(error, result)) return;
  presentProblemNotification(t, error, { unmapped: result.unmapped });
}
