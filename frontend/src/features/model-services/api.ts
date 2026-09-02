import { apiClient } from "@/lib/api";
import type { OffsetPage, PageQuery } from "@/lib/pagination";
import type {
  ModelService,
  ModelServiceTestResult,
  ModelServiceWrite,
  PurposeState,
  RebuildChoice,
} from "@/features/model-services/types";

function pageSuffix(params?: PageQuery): string {
  const qs = new URLSearchParams();
  if (params?.limit != null) qs.set("limit", String(params.limit));
  if (params?.offset != null) qs.set("offset", String(params.offset));
  const query = qs.toString();
  return query ? `?${query}` : "";
}

export function listModelServices(params?: PageQuery) {
  return apiClient<OffsetPage<ModelService>>(
    `/model-services${pageSuffix(params)}`,
  );
}

export function getModelService(id: string) {
  return apiClient<ModelService>(`/model-services/${id}`);
}

export function getEmbeddingPurpose() {
  return apiClient<PurposeState>("/model-services/purpose/embedding");
}

export function createModelService(body: ModelServiceWrite) {
  return apiClient<ModelService>("/model-services", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      purpose: "embedding",
      protocol: "openai_compat",
      ...body,
    }),
  });
}

export function patchModelService(id: string, body: ModelServiceWrite) {
  return apiClient<ModelService>(`/model-services/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function testModelService(id: string) {
  return apiClient<ModelServiceTestResult>(`/model-services/${id}/test`, {
    method: "POST",
  });
}

export function activateModelService(id: string) {
  return apiClient<ModelService>(`/model-services/${id}/activate`, {
    method: "POST",
  });
}

export function deleteModelService(id: string) {
  return apiClient<void>(`/model-services/${id}`, { method: "DELETE" });
}

export function closeEmbeddingPurpose() {
  return apiClient<PurposeState>("/model-services/purpose/embedding/close", {
    method: "POST",
  });
}

export function openEmbeddingPurpose(rebuild: RebuildChoice) {
  return apiClient<PurposeState>("/model-services/purpose/embedding/open", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ rebuild }),
  });
}

export function cleanupEmbeddingPurpose() {
  return apiClient<PurposeState>("/model-services/purpose/embedding/cleanup", {
    method: "POST",
  });
}

export function reindexEmbeddingPurpose() {
  return apiClient<PurposeState>("/model-services/purpose/embedding/reindex", {
    method: "POST",
  });
}
