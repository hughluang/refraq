"use client";

import { useTranslate } from "@refinedev/core";
import { useCallback, useRef } from "react";

import { presentProblemNotification } from "@/components/feedback/presentProblemNotification";
import {
  usePagedList,
  type UsePagedListOptions,
  type UsePagedListResult,
} from "@/hooks/usePagedList";

/** HTTP Console Offset Page lists: one problem notification with retry. */
export function useConsolePagedList<T>(
  options: Omit<UsePagedListOptions<T>, "onError">,
): UsePagedListResult<T> {
  const translate = useTranslate();
  const translateRef = useRef(translate);
  translateRef.current = translate;
  const reloadRef = useRef<() => Promise<void>>(async () => {});
  const onError = useCallback((error: unknown) => {
    presentProblemNotification(translateRef.current, error, {
      onRetry: () => {
        void reloadRef.current();
      },
    });
  }, []);
  const list = usePagedList({ ...options, onError });
  reloadRef.current = list.reload;
  return list;
}
