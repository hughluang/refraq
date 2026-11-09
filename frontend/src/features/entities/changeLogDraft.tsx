"use client";

import {
  createContext,
  useContext,
  useMemo,
  useState,
  type Dispatch,
  type ReactNode,
  type SetStateAction,
} from "react";

export type ChangeLogFilters = {
  operation: string;
  source: string;
  subject: string;
  rowIdentity: string;
  versionId: string;
  rowId: string;
  occurredFrom: string;
  occurredTo: string;
};

export const EMPTY_CHANGE_LOG_FILTERS: ChangeLogFilters = {
  operation: "",
  source: "",
  subject: "",
  rowIdentity: "",
  versionId: "",
  rowId: "",
  occurredFrom: "",
  occurredTo: "",
};

type ChangeLogDraft = {
  filters: ChangeLogFilters;
  setFilters: Dispatch<SetStateAction<ChangeLogFilters>>;
};

const ChangeLogDraftContext = createContext<ChangeLogDraft | null>(null);

export function ChangeLogDraftProvider({ children }: { children: ReactNode }) {
  const [filters, setFilters] = useState<ChangeLogFilters>(EMPTY_CHANGE_LOG_FILTERS);
  const value = useMemo(() => ({ filters, setFilters }), [filters]);
  return (
    <ChangeLogDraftContext.Provider value={value}>{children}</ChangeLogDraftContext.Provider>
  );
}

export function useChangeLogDraft(): ChangeLogDraft {
  const draft = useContext(ChangeLogDraftContext);
  if (draft == null) {
    throw new Error("ChangeLogDraftProvider is missing");
  }
  return draft;
}
