export type JoinSelectOption = { value: string; label: string };

export type JoinDraftIssue =
  | "catalog.joins.evidenceRequired"
  | "catalog.joins.toColumnRequired";

export type JoinDraftValidation =
  | { ok: true; evidence: string; fromId: string; toId: string }
  | { ok: false; messageKey: JoinDraftIssue };

export function validateJoinDraft(input: {
  evidence: string;
  fromId: string | null;
  toId: string | null;
}): JoinDraftValidation {
  const evidence = input.evidence.trim();
  if (!evidence) {
    return { ok: false, messageKey: "catalog.joins.evidenceRequired" };
  }
  if (!input.fromId || !input.toId) {
    return { ok: false, messageKey: "catalog.joins.toColumnRequired" };
  }
  return { ok: true, evidence, fromId: input.fromId, toId: input.toId };
}

export function isAutoDerivedJoin(origin: string | null | undefined): boolean {
  return origin === "foreign_key";
}

export function columnOptionLabel(name: string, locatorKey: string): string {
  return `${name} · ${locatorKey}`;
}

export function columnLabel(
  columns: ReadonlyArray<{
    id: string;
    name: string;
    locator_key: string;
  }>,
  columnId: string,
): string {
  const col = columns.find((c) => c.id === columnId);
  if (!col) return columnId;
  return columnOptionLabel(col.name, col.locator_key);
}

export function retainSelectedOption(
  previous: ReadonlyArray<JoinSelectOption>,
  selectedId: string | null,
): JoinSelectOption[] {
  if (!selectedId) return [];
  return previous.filter((o) => o.value === selectedId);
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
