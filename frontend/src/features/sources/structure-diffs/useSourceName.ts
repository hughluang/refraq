"use client";

import { useEffect, useState } from "react";

import { getSource } from "@/features/sources/api/sources";

export type SourceNameState = {
  name: string | null;
  failed: boolean;
};

/** Source name for a page title. `failed` is set when the Source cannot be loaded. */
export function useSourceName(sourceId: string): SourceNameState {
  const [state, setState] = useState<SourceNameState>({ name: null, failed: false });
  useEffect(() => {
    let cancelled = false;
    setState({ name: null, failed: false });
    void getSource(sourceId)
      .then((res) => {
        if (!cancelled) setState({ name: res.source.name, failed: false });
      })
      .catch(() => {
        if (!cancelled) setState({ name: null, failed: true });
      });
    return () => {
      cancelled = true;
    };
  }, [sourceId]);
  return state;
}
