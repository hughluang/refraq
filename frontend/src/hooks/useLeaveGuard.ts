"use client";

import { useEffect, useRef } from "react";

import { LEAVE_GUARD_ALLOW, isLeaveHref } from "@/hooks/leaveGuard";

type Options = {
  enabled: boolean;
  message: string;
};

export function useLeaveGuard({ enabled, message }: Options): {
  bypass: () => void;
} {
  const enabledRef = useRef(enabled);
  const messageRef = useRef(message);
  const bypassRef = useRef(false);
  enabledRef.current = enabled;
  messageRef.current = message;

  useEffect(() => {
    const shouldBlock = () => enabledRef.current && !bypassRef.current;

    const onBeforeUnload = (event: BeforeUnloadEvent) => {
      if (!shouldBlock()) return;
      event.preventDefault();
      event.returnValue = messageRef.current;
    };

    const onClick = (event: MouseEvent) => {
      if (!shouldBlock()) return;
      if (event.defaultPrevented || event.button !== 0) return;
      if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) {
        return;
      }
      const target = event.target;
      if (!(target instanceof Element)) return;
      const anchor = target.closest("a[href]");
      if (!(anchor instanceof HTMLAnchorElement)) return;
      if (anchor.dataset.leaveGuard === LEAVE_GUARD_ALLOW) return;
      if (anchor.target === "_blank") return;
      if (!isLeaveHref(window.location.href, anchor.href)) return;
      if (!window.confirm(messageRef.current)) {
        event.preventDefault();
        event.stopPropagation();
      }
    };

    window.addEventListener("beforeunload", onBeforeUnload);
    document.addEventListener("click", onClick, true);
    return () => {
      window.removeEventListener("beforeunload", onBeforeUnload);
      document.removeEventListener("click", onClick, true);
    };
  }, []);

  return {
    bypass: () => {
      bypassRef.current = true;
    },
  };
}
