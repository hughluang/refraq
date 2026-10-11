import { apiClient } from "@/lib/api";
import type { OffsetPage } from "@/lib/pagination";

import type {
  Channel,
  ChannelDraft,
  ChannelRun,
  ChannelRunDetail,
  ChannelVersion,
  Confirmation,
  Graph,
  GraphProblem,
  NodeTypeSpec,
  RefinedPort,
} from "@/features/channels/types";

function querySuffix(
  params?: Record<string, string | number | boolean | undefined>,
) {
  const qs = new URLSearchParams();
  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value === undefined || value === "") continue;
      qs.set(key, String(value));
    }
  }
  const encoded = qs.toString();
  return encoded ? `?${encoded}` : "";
}

export function listNodeTypes() {
  return apiClient<{ items: NodeTypeSpec[] }>("/channel-node-types");
}

export function listChannels(params?: {
  q?: string;
  active?: boolean;
  limit?: number;
  offset?: number;
}) {
  return apiClient<OffsetPage<Channel>>(`/channels${querySuffix(params)}`);
}

export function createChannel(body: { name: string; description: string | null }) {
  return apiClient<{ channel: Channel }>("/channels", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function getChannel(id: string) {
  return apiClient<{ channel: Channel }>(`/channels/${id}`);
}

export function patchChannel(
  id: string,
  body: { name?: string; description?: string | null },
) {
  return apiClient<{ channel: Channel }>(`/channels/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function activateChannel(id: string) {
  return apiClient<{ channel: Channel }>(`/channels/${id}/activate`, {
    method: "POST",
  });
}

export function deactivateChannel(id: string) {
  return apiClient<{ channel: Channel }>(`/channels/${id}/deactivate`, {
    method: "POST",
  });
}

export function deleteChannel(id: string) {
  return apiClient<void>(`/channels/${id}`, { method: "DELETE" });
}

export function getDraft(id: string) {
  return apiClient<ChannelDraft>(`/channels/${id}/draft`);
}

export function saveDraft(
  id: string,
  body: { base_revision: number; graph: Graph },
) {
  return apiClient<ChannelDraft>(`/channels/${id}/draft`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function validateDraft(id: string) {
  return apiClient<{
    draft_revision: number;
    valid: boolean;
    problems: GraphProblem[];
    ports: RefinedPort[];
  }>(`/channels/${id}/draft/validate`, { method: "POST" });
}

export function previewPublish(id: string) {
  return apiClient<Confirmation>(`/channels/${id}/publish/preview`, {
    method: "POST",
  });
}

export function publishChannel(id: string, draftRevision: number) {
  return apiClient<{ version: ChannelVersion; confirmation: Confirmation }>(
    `/channels/${id}/publish`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ draft_revision: draftRevision }),
    },
  );
}

export function startRun(
  id: string,
  body: { target: "draft" | "published"; trigger_node_id?: string; ignore_checkpoints?: boolean },
) {
  return apiClient<{ run: ChannelRun }>(`/channels/${id}/runs`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function listRuns(
  id: string,
  params?: { status?: string; target?: string; limit?: number; offset?: number },
) {
  return apiClient<OffsetPage<ChannelRun>>(`/channels/${id}/runs${querySuffix(params)}`);
}

export function getRun(id: string, jobId: string) {
  return apiClient<ChannelRunDetail>(`/channels/${id}/runs/${jobId}`);
}

export function listVersions(
  id: string,
  params?: { limit?: number; offset?: number },
) {
  return apiClient<OffsetPage<ChannelVersion>>(
    `/channels/${id}/versions${querySuffix(params)}`,
  );
}
