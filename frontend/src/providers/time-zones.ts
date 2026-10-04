"use client";

import { useEffect, useState } from "react";

import { apiClient } from "@/lib/api";

export type TimeZoneItem = {
  id: string;
  aliases: string[];
};

type TimeZoneList = {
  items: TimeZoneItem[];
};

let cached: TimeZoneItem[] | null = null;
let inflight: Promise<TimeZoneItem[]> | null = null;

export function loadTimeZones(): Promise<TimeZoneItem[]> {
  if (cached) {
    return Promise.resolve(cached);
  }
  if (!inflight) {
    inflight = apiClient<TimeZoneList>("/time-zones")
      .then((body) => {
        cached = body.items;
        return body.items;
      })
      .finally(() => {
        inflight = null;
      });
  }
  return inflight;
}

export function useTimeZones() {
  const [items, setItems] = useState<TimeZoneItem[]>(cached ?? []);
  const [loading, setLoading] = useState(cached === null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(cached === null);
    loadTimeZones()
      .then((loaded) => {
        if (cancelled) return;
        setItems(loaded);
        setError(null);
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return { items, loading, error };
}
