import { apiClient } from "@/lib/api";

import type { DictionaryListStatus } from "@/features/dictionaries/dictionaryListFilter";
import type {
  Dictionary,
  DictionaryCreateBody,
  DictionaryPatchBody,
} from "@/features/dictionaries/types";
import type { OffsetPage } from "@/lib/pagination";

function querySuffix(
  params?: Record<string, string | number | readonly string[] | undefined>,
) {
  const qs = new URLSearchParams();
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === "") continue;
      if (Array.isArray(value)) {
        for (const item of value) {
          qs.append(key, item);
        }
        continue;
      }
      qs.set(key, String(value));
    }
  }
  const encoded = qs.toString();
  return encoded ? `?${encoded}` : "";
}

export function listDictionaries(params?: {
  q?: string;
  status?: readonly DictionaryListStatus[];
  limit?: number;
  offset?: number;
  signal?: AbortSignal;
}) {
  const { signal, ...query } = params ?? {};
  return apiClient<OffsetPage<Dictionary>>(`/dictionaries${querySuffix(query)}`, {
    signal,
  });
}

export function getDictionary(id: string, init?: { signal?: AbortSignal }) {
  return apiClient<{ dictionary: Dictionary }>(`/dictionaries/${id}`, {
    signal: init?.signal,
  });
}

export function createDictionary(body: DictionaryCreateBody) {
  return apiClient<{ dictionary: Dictionary }>("/dictionaries", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function patchDictionary(id: string, body: DictionaryPatchBody) {
  return apiClient<{ dictionary: Dictionary }>(`/dictionaries/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function deleteDictionary(id: string) {
  return apiClient<void>(`/dictionaries/${id}`, { method: "DELETE" });
}
