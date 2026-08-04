"use client";

import { create } from "zustand";

import { fetchModuleIdentities } from "@/features/console/module-identity/api";
import type { ModuleIdentity } from "@/features/console/module-identity/types";
import { ApiError } from "@/lib/api";

export type ModuleIdentityStatus = "idle" | "loading" | "ready" | "error";

type ModuleIdentityState = {
  status: ModuleIdentityStatus;
  modules: ModuleIdentity[];
  error: string | null;
  load: () => Promise<void>;
  reset: () => void;
};

export const useModuleIdentityStore = create<ModuleIdentityState>((set, get) => ({
  status: "idle",
  modules: [],
  error: null,
  async load() {
    if (get().status === "loading") return;
    set({ status: "loading", error: null });
    try {
      const data = await fetchModuleIdentities();
      set({ status: "ready", modules: data.modules, error: null });
    } catch (error) {
      set({
        status: "error",
        modules: [],
        error:
          error instanceof ApiError ? error.detail : "module_identity_load_failed",
      });
    }
  },
  reset() {
    set({ status: "idle", modules: [], error: null });
  },
}));

export function getModuleIdentities(): ModuleIdentity[] {
  return useModuleIdentityStore.getState().modules;
}

export function getModuleIdentityStatus(): ModuleIdentityStatus {
  return useModuleIdentityStore.getState().status;
}
