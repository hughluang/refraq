"use client";

import { createContext, useContext, useMemo, type ReactNode } from "react";

import type { NavigationGroup } from "@/features/console/types";

export type ConsoleNavData = {
  groups: NavigationGroup[];
  ready: boolean;
  toggleNavigation: () => void;
};

const EMPTY: ConsoleNavData = {
  groups: [],
  ready: false,
  toggleNavigation: () => {},
};

const ConsoleNavDataContext = createContext<ConsoleNavData>(EMPTY);

export function ConsoleNavDataProvider({
  groups,
  ready,
  toggleNavigation,
  children,
}: ConsoleNavData & { children: ReactNode }) {
  const value = useMemo(
    () => ({ groups, ready, toggleNavigation }),
    [groups, ready, toggleNavigation],
  );
  return (
    <ConsoleNavDataContext.Provider value={value}>
      {children}
    </ConsoleNavDataContext.Provider>
  );
}

export function useConsoleNavData(): ConsoleNavData {
  return useContext(ConsoleNavDataContext);
}
