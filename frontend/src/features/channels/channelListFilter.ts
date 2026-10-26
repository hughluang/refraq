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
