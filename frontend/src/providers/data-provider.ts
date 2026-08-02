import type { DataProvider } from "@refinedev/core";

import { apiClient, ApiError } from "@/lib/api";

const RESOURCE_BASE_URL: Record<string, string> = {
  users: "users",
  roles: "roles",
  permissions: "permissions",
};

function resourceBaseUrl(resource: string): string {
  return RESOURCE_BASE_URL[resource] ?? resource;
}

type CrudParams<TVariables = Record<string, unknown>> = {
  resource: string;
  id?: string | number;
  variables?: TVariables;
  meta?: Record<string, unknown>;
};

type GetListParams = CrudParams & {
  pagination?: { current?: number; pageSize?: number; mode?: string };
  filters?: unknown[];
  sorters?: unknown[];
};

type GetListResult<T> = { data: T[]; total: number };

function unwrapEntity<T>(
  resource: string,
  payload: Record<string, unknown>,
): T {
  if (resource === "users" && "user" in payload) {
    return payload.user as T;
  }
  if (resource === "roles" && "role" in payload) {
    return payload.role as T;
  }
  return payload as unknown as T;
}

function statusAction(resource: string, meta?: Record<string, unknown>): string | null {
  if (resource === "users" && meta && (meta as { action?: string }).action === "status") {
    return "status";
  }
  return null;
}

export const dataProvider: DataProvider = {
  getApiUrl() {
    return process.env.NEXT_PUBLIC_REFRAQ_API_BASE_URL || "/api";
  },

  async getList<T = Record<string, unknown>>(params: GetListParams): Promise<GetListResult<T>> {
    const base = resourceBaseUrl(params.resource);
    const data = await apiClient<{ items: T[] }>(`/${base}`);
    return {
      data: data.items,
      total: data.items.length,
    };
  },

  async getOne<T = Record<string, unknown>>(params: CrudParams): Promise<{ data: T }> {
    const base = resourceBaseUrl(params.resource);
    if (params.resource === "roles") {
      const data = await apiClient<Record<string, unknown>>(`/${base}/${params.id}`);
      return { data: unwrapEntity<T>(params.resource, data) };
    }
    throw new ApiError(
      405,
      "GET_ONE_UNSUPPORTED",
      `v1 does not support GET /${base}/{id}`,
    );
  },

  async create<T = Record<string, unknown>, TVariables = Record<string, unknown>>(
    params: CrudParams<TVariables>,
  ): Promise<{ data: T }> {
    const base = resourceBaseUrl(params.resource);
    const data = await apiClient<Record<string, unknown>>(`/${base}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(params.variables ?? {}),
    });
    return { data: unwrapEntity<T>(params.resource, data) };
  },

  async update<T = Record<string, unknown>, TVariables = Record<string, unknown>>(
    params: CrudParams<TVariables>,
  ): Promise<{ data: T }> {
    const base = resourceBaseUrl(params.resource);
    const action = statusAction(params.resource, params.meta);
    const path = action ? `/${base}/${params.id}/${action}` : `/${base}/${params.id}`;
    const data = await apiClient<Record<string, unknown>>(path, {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(params.variables ?? {}),
    });
    return { data: unwrapEntity<T>(params.resource, data) };
  },

  async deleteOne<T = Record<string, unknown>, TVariables = Record<string, unknown>>(
    params: CrudParams<TVariables>,
  ): Promise<{ data: T }> {
    const base = resourceBaseUrl(params.resource);
    const data = await apiClient<T>(`/${base}/${params.id}`, { method: "DELETE" });
    return { data: (data ?? { id: params.id }) as T };
  },
};
