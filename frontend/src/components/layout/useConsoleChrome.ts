"use client";

import { useDisclosure } from "@mantine/hooks";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  CONSOLE_MAIN_ID,
  isChannelCanvasTarget,
  isEditableShortcutTarget,
  NAV_MODE_KEY,
} from "@/components/layout/consoleNav";

export function useNavMode() {
  const [rail, setRail] = useState(false);

  useEffect(() => {
    setRail(window.localStorage.getItem(NAV_MODE_KEY) === "rail");
  }, []);

  const toggle = useCallback(() => {
    setRail((current) => {
      const next = !current;
      window.localStorage.setItem(NAV_MODE_KEY, next ? "rail" : "expanded");
      return next;
    });
  }, []);

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "[") return;
      if (event.ctrlKey || event.metaKey || event.altKey) return;
      if (isEditableShortcutTarget(event.target)) return;
      if (isChannelCanvasTarget(event.target)) return;
      event.preventDefault();
      toggle();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggle]);

  return { rail, toggle };
}

export function useNavOverlay(pathname: string) {
  const [opened, { toggle, close }] = useDisclosure(false);
  const menuRef = useRef<HTMLButtonElement>(null);
  const seen = useRef<string | null>(null);
  const openedRef = useRef(opened);
  openedRef.current = opened;

  useEffect(() => {
    if (seen.current === null) {
      seen.current = pathname;
      return;
    }
    if (seen.current === pathname) return;
    seen.current = pathname;
    if (!openedRef.current) return;
    close();
  }, [pathname, close]);

  useEffect(() => {
    if (!opened) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      close();
      menuRef.current?.focus();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [opened, close]);

  return { opened, toggle, close, menuRef };
}

export function usePageHeadingFocus(pathname: string) {
  const seen = useRef<string | null>(null);

  useEffect(() => {
    if (seen.current === null) {
      seen.current = pathname;
      return;
    }
    if (seen.current === pathname) return;
    seen.current = pathname;
    const root = document.getElementById(CONSOLE_MAIN_ID) as HTMLElement;
    let focused: HTMLElement | null = null;
    const run = () => {
      const heading = root.querySelector<HTMLElement>("[data-page-heading]");
      if (!heading || heading === focused) return;
      focused = heading;
      heading.tabIndex = -1;
      heading.focus();
      const scroller = root.querySelector<HTMLElement>("[data-page-scroll]");
      scroller?.scrollTo({ top: 0 });
    };
    run();
    const observer = new MutationObserver(run);
    observer.observe(root, { childList: true, subtree: true });
    return () => observer.disconnect();
  }, [pathname]);
}
