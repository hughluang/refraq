import { apiClient } from "@/lib/api";

export type DataProvider = {
  getList: (resource: string) => Promise<unknown>;
};

export const dataProvider: DataProvider = {
  async getList(resource) {
    return apiClient(resource);
  },
};
