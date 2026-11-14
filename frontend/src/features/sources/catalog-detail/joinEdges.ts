export type JoinSelectOption = { value: string; label: string };

export type JoinRowState = "rejected" | "automated" | "manual";

export function joinRowState(join: {
  created_by_user_id?: string | null;
  is_rejected?: boolean | null;
}): JoinRowState {
  if (join.is_rejected) return "rejected";
  if (!join.created_by_user_id) return "automated";
  return "manual";
}

export function joinRowActions(state: JoinRowState): {
  amend: boolean;
  reject: boolean;
  restore: boolean;
  delete: boolean;
} {
  if (state === "rejected") {
    return { amend: false, reject: false, restore: true, delete: false };
  }
  return {
    amend: true,
    reject: true,
    restore: false,
    delete: state === "manual",
  };
}

export function objectRefFromColumnLocator(
  locator: string | null | undefined,
): string | null {
  if (!locator || !locator.startsWith("col/")) return null;
  const parts = locator.split("/");
  if (parts.length !== 8 || parts[6] !== "column" || parts.some((part) => !part)) return null;
  return `obj/${parts[1]}/${parts[2]}/${parts[3]}/${parts[4]}/${parts[5]}`;
}

export function mergeSelectedOption(
  next: JoinSelectOption[],
  selectedId: string | null,
  previous: ReadonlyArray<JoinSelectOption>,
): JoinSelectOption[] {
  if (!selectedId || next.some((o) => o.value === selectedId)) return next;
  const selected = previous.find((o) => o.value === selectedId);
  return selected ? [selected, ...next] : next;
}
