"use client";

import { useCallback, useState } from "react";

export function useConfirmAction<T>() {
  const [pending, setPending] = useState<T | null>(null);
  const open = useCallback((item: T) => {
    setPending(item);
  }, []);
  const close = useCallback(() => {
    setPending(null);
  }, []);
  return { pending, opened: pending != null, open, close };
}
