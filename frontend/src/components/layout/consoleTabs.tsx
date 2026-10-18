"use client";

import { Tabs } from "@mantine/core";
import { useSearchParams } from "next/navigation";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";

export type PageTabItem = {
  value: string;
  label: ReactNode;
  panel: ReactNode;
};

/**
 * `tab` comes from Next's search params. Selecting a tab writes with
 * `history.replaceState` (no history entry) and updates local state immediately.
 * A later search-params change, including back/forward that Next reports, wins.
 * An unknown value resolves to the first tab.
 */
export function useConsoleTab(tabs: readonly { value: string }[]) {
  const searchParams = useSearchParams();
  const queryTab = searchParams.get("tab");
  const valuesKey = tabs.map((tab) => tab.value).join("\0");
  const tabsRef = useRef(tabs);
  tabsRef.current = tabs;
  const [selected, setSelected] = useState(() => resolveConsoleTab(tabs, queryTab));

  useEffect(() => {
    setSelected(resolveConsoleTab(tabsRef.current, queryTab));
  }, [queryTab, valuesKey]);

  const setTab = useCallback((next: string) => {
    const resolved = resolveConsoleTab(tabsRef.current, next);
    setSelected(resolved);
    const url = new URL(window.location.href);
    url.searchParams.set("tab", resolved);
    const href = `${url.pathname}${url.search}${url.hash}`;
    window.history.replaceState(window.history.state, "", href);
  }, []);

  return { value: selected, setTab };
}

export function resolveConsoleTab(
  tabs: readonly { value: string }[],
  raw: string | null,
): string {
  if (raw && tabs.some((tab) => tab.value === raw)) return raw;
  return tabs[0]?.value ?? "";
}

export function PageTabs({
  tabs,
  value,
  onChange,
  fill = false,
  children,
}: {
  tabs: readonly PageTabItem[];
  value: string;
  onChange: (value: string) => void;
  /** Active panel fills a remaining-space column. */
  fill?: boolean;
  children: (slots: { list: ReactNode; panels: ReactNode }) => ReactNode;
}) {
  const setTab = onChange;
  const [visited, setVisited] = useState<string[]>([]);
  if (value && !visited.includes(value)) {
    setVisited([...visited, value]);
  }

  const list = (
    <Tabs
      value={value || null}
      onChange={(next) => {
        if (next) setTab(next);
      }}
    >
      <Tabs.List>
        {tabs.map((tab) => (
          <Tabs.Tab key={tab.value} value={tab.value}>
            {tab.label}
          </Tabs.Tab>
        ))}
      </Tabs.List>
    </Tabs>
  );

  const panels = tabs.map((tab) => {
    if (!visited.includes(tab.value)) return null;
    const active = tab.value === value;
    return (
      <div
        key={tab.value}
        hidden={!active}
        data-tab-panel={tab.value}
        style={
          active
            ? {
                paddingTop: "var(--mantine-spacing-md)",
                ...(fill
                  ? {
                      flex: "1 1 auto",
                      minHeight: 0,
                      display: "flex",
                      flexDirection: "column",
                      overflow: "auto",
                    }
                  : null),
              }
            : undefined
        }
      >
        {tab.panel}
      </div>
    );
  });

  return children({ list, panels });
}
