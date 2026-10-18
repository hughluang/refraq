import type { ReactNode } from "react";

export type FieldTone = "error" | "warning" | "info";

export type FieldNote = {
  text: ReactNode;
  tone: FieldTone;
};

export type FieldChromeProps = {
  notes?: readonly FieldNote[];
  openSignal?: string | null;
  bare?: boolean;
  /** Persistent guidance under the input. Distinct from the reference popover. */
  helper?: ReactNode;
};

export function joinDescribedBy(...ids: Array<string | undefined>): string | undefined {
  const value = ids
    .flatMap((id) => (id ? id.split(/\s+/) : []))
    .filter(Boolean)
    .join(" ");
  return value || undefined;
}

const RANK: Record<FieldTone, number> = { error: 0, warning: 1, info: 2 };

export function collectNotes(
  error: ReactNode | undefined,
  notes: readonly FieldNote[] | undefined,
): FieldNote[] {
  const head: FieldNote[] = [];
  if (typeof error === "string") {
    if (error.trim()) head.push({ text: error, tone: "error" });
  } else if (error != null && error !== false && error !== true) {
    head.push({ text: error, tone: "error" });
  }
  return [...head, ...(notes ?? [])];
}

export function noteTone(notes: readonly FieldNote[]): FieldTone | null {
  if (notes.some((note) => note.tone === "error")) return "error";
  if (notes.some((note) => note.tone === "warning")) return "warning";
  if (notes.length > 0) return "info";
  return null;
}

export function orderedNotes(notes: readonly FieldNote[]): FieldNote[] {
  return [...notes].sort((left, right) => RANK[left.tone] - RANK[right.tone]);
}

export function presentDescription(description: ReactNode | undefined): ReactNode | undefined {
  if (description == null || description === false) return undefined;
  if (typeof description === "string" && description.trim() === "") return undefined;
  return description;
}
