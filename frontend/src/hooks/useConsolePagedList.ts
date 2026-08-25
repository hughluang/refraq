"use client";

import { useNotification } from "@refinedev/core";
import { useCallback } from "react";

import {
  usePagedList,
  type UsePagedListOptions,
  type UsePagedListResult,
} from "@/hooks/usePagedList";

/** HTTP Console Offset Page lists: Refine toast through `usePagedList` `onError`. */
export function useConsolePagedList<T>(
  options: Omit<UsePagedListOptions<T>, "onError">,
): UsePagedListResult<T> {
  const { open } = useNotification();
  const onError = useCallback(
    (message: string) => {
      open?.({ type: "error", message });
    },
    [open],
  );
  return usePagedList({ ...options, onError });
}
