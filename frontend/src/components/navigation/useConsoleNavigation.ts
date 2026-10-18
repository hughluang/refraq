"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useId, useSyncExternalStore, useTransition } from "react";

import {
  confirmLeave,
  navigationNeedsConfirm,
} from "@/components/navigation/leaveGuard";
import {
  getNavigationPending,
  setNavigationPending,
  subscribeNavigationPending,
} from "@/components/navigation/navigationPending";

export type ConsoleNavigation = {
  push: (href: string) => void;
  replace: (href: string) => void;
  refresh: () => void;
  /** True while a console hook transition or console link navigation is pending. */
  pending: boolean;
};

function runGuarded(href: string, run: () => void) {
  if (!navigationNeedsConfirm(href)) {
    run();
    return;
  }
  void confirmLeave().then((allowed) => {
    if (allowed) run();
  });
}

export function useConsoleNavigation(): ConsoleNavigation {
  const router = useRouter();
  const id = useId();
  const [isPending, startTransition] = useTransition();
  const pending = useSyncExternalStore(
    subscribeNavigationPending,
    getNavigationPending,
    () => false,
  );

  useEffect(() => {
    setNavigationPending(id, isPending);
    return () => setNavigationPending(id, false);
  }, [id, isPending]);

  const push = useCallback(
    (href: string) => {
      runGuarded(href, () => {
        startTransition(() => {
          router.push(href);
        });
      });
    },
    [router],
  );

  const replace = useCallback(
    (href: string) => {
      runGuarded(href, () => {
        startTransition(() => {
          router.replace(href);
        });
      });
    },
    [router],
  );

  const refresh = useCallback(() => {
    startTransition(() => {
      router.refresh();
    });
  }, [router]);

  return { push, replace, refresh, pending };
}
