"use client";

import { create } from "zustand";

export type CurrentUser = {
  id: string;
  account: string;
  display_name: string;
  email: string | null;
  locale: string;
  role_id: string | null;
  role_key: string | null;
  role_name: string | null;
  permissions: string[];
  identity_source: "local";
};

type SessionState = {
  user: CurrentUser | null;
  /** True after local clear(); skips /auth/me until setUser() runs. */
  signedOutLocally: boolean;
  setUser: (user: CurrentUser | null) => void;
  clear: () => void;
};

export const useSessionStore = create<SessionState>((set) => ({
  user: null,
  signedOutLocally: false,
  setUser: (user) => set({ user, signedOutLocally: false }),
  clear: () => set({ user: null, signedOutLocally: true }),
}));

export function getCurrentUser(): CurrentUser | null {
  return useSessionStore.getState().user;
}

export function isSignedOutLocally(): boolean {
  return useSessionStore.getState().signedOutLocally;
}
