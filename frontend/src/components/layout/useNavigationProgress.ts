"use client";

import { nprogress } from "@mantine/nprogress";
import { useEffect, useSyncExternalStore } from "react";

import {
  getNavigationPending,
  subscribeNavigationPending,
} from "@/components/navigation/navigationPending";

export const NAV_PROGRESS_DELAY_MS = 150;

export function useNavigationProgress() {
  const pending = useSyncExternalStore(
    subscribeNavigationPending,
    getNavigationPending,
    () => false,
  );

  useEffect(() => {
    if (!pending) {
      nprogress.complete();
      return;
    }
    const timer = window.setTimeout(() => {
      nprogress.start();
    }, NAV_PROGRESS_DELAY_MS);
    return () => {
      window.clearTimeout(timer);
    };
  }, [pending]);
}
