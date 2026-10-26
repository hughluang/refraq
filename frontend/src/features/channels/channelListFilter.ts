import { apiClient } from "@/lib/api";

export type ChannelListRequest = {
  q?: string;
  active?: boolean;
  tag_id?: string[];
  limit: number;
  offset: number;
};

/** Query the Channel list sends. Activation and Tags stay omitted until chosen. */
export function channelListRequest(input: {
  q: string;
  active: string;
  tagIds: readonly string[];
  limit: number;
  offset: number;
}): ChannelListRequest {
  const request: ChannelListRequest = {
    limit: input.limit,
    offset: input.offset,
  };
  const q = input.q.trim();
  if (q !== "") request.q = q;
  if (input.active === "true") request.active = true;
  else if (input.active === "false") request.active = false;
  const tagIds = input.tagIds.filter((id) => id !== "");
  if (tagIds.length > 0) request.tag_id = [...tagIds];
  return request;
}

export type ChannelSavedQuery = {
  q: string;
  active: boolean | null;
  tag_ids: string[];
};

function collapse(values: readonly string[]): string[] {
  const seen: string[] = [];
  for (const item of values) {
    if (!seen.includes(item)) seen.push(item);
  }
  return seen;
}

function storedActive(value: string): boolean | null {
  if (value === "true") return true;
  if (value === "false") return false;
  return null;
}

/** Query stored on a Saved Filter. Offset is a page, not part of the filter. */
export function channelSavedQuery(input: {
  q: string;
  active: string;
  tagIds: readonly string[];
}): ChannelSavedQuery {
  return {
    q: input.q.trim(),
    active: storedActive(input.active),
    tag_ids: collapse(input.tagIds.filter((id) => id !== "")),
  };
}

export type StoredChannelFilter = {
  id: string;
  query: ChannelSavedQuery;
};

export function sameChannelSavedQuery(
  left: ChannelSavedQuery,
  right: ChannelSavedQuery,
): boolean {
  if (left.q !== right.q || left.active !== right.active) return false;
  if (left.tag_ids.length !== right.tag_ids.length) return false;
  const orderedLeft = [...left.tag_ids].sort();
  const orderedRight = [...right.tag_ids].sort();
  return orderedLeft.every((item, index) => item === orderedRight[index]);
}

/** See `entitySaveTarget`. Applied, then a stored query equal to the controls. */
export function channelSaveTarget(input: {
  appliedId: string | null;
  stored: readonly StoredChannelFilter[];
  current: ChannelSavedQuery;
}): { kind: "update"; id: string } | { kind: "create" } {
  if (input.appliedId) return { kind: "update", id: input.appliedId };
  const match = input.stored.find((item) =>
    sameChannelSavedQuery(item.query, input.current),
  );
  if (match) return { kind: "update", id: match.id };
  return { kind: "create" };
}

export type ChannelSavedFilter = {
  id: string;
  name: string;
  query: ChannelSavedQuery;
};

type ChannelSavedFilterWire = ChannelSavedFilter & {
  list: string;
  created_at: string;
  updated_at: string;
};

function asChannelFilter(record: ChannelSavedFilterWire): ChannelSavedFilter {
  return { id: record.id, name: record.name, query: record.query };
}

/** The caller's Channel filters and the one remembered for the next visit. */
export async function loadChannelSavedFilters(): Promise<{
  filters: ChannelSavedFilter[];
  rememberedId: string | null;
}> {
  const [page, memory] = await Promise.all([
    apiClient<{ items: ChannelSavedFilterWire[] }>(
      "/saved-filters?list=channels&limit=50",
    ),
    apiClient<{ saved_filter_id: string | null }>(
      "/saved-filters/default?list=channels",
    ),
  ]);
  const filters = page.items.map(asChannelFilter);
  const rememberedId = filters.some((item) => item.id === memory.saved_filter_id)
    ? memory.saved_filter_id
    : null;
  return { filters, rememberedId };
}

export function createChannelSavedFilter(name: string, query: ChannelSavedQuery) {
  return apiClient<{ saved_filter: ChannelSavedFilterWire }>("/saved-filters", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ list: "channels", name, query }),
  });
}

export function patchChannelSavedFilter(
  id: string,
  body: { name?: string; query: ChannelSavedQuery },
) {
  return apiClient<{ saved_filter: ChannelSavedFilterWire }>(
    `/saved-filters/${id}`,
    {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    },
  );
}

export function rememberChannelSavedFilter(id: string | null) {
  return apiClient<{ saved_filter_id: string | null }>("/saved-filters/default", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ list: "channels", saved_filter_id: id }),
  });
}
