"use client";

import { create } from "zustand";
import { createJSONStorage, persist } from "zustand/middleware";

export type CurrentUser = {
  id: string;
  account: string;
  display_name: string;
  email: string | null;
  locale: string;
  /** IANA zone for Console Instant formatting; null = follow browser. */
  display_timezone: string | null;
  role_id: string | null;
  role_key: string | null;
  role_name: string | null;
  permissions: string[];
  identity_source: "local" | "oidc";
};

/** Tab-scoped UX snapshot only — never includes permissions or PII beyond display. */
export type UserDisplaySummary = {
  id: string;
  account: string;
  display_name: string;
  locale: string;
  display_timezone: string | null;
};

const PERSIST_KEY = "refraq.console.user-display";

type PersistedSlice = {
  display: UserDisplaySummary | null;
};

type SessionState = {
  user: CurrentUser | null;
  /**
   * True after login or successful GET /auth/me this tab lifetime.
   * False when only a display summary was restored from sessionStorage.
   */
  permissionsReady: boolean;
  /**
   * Non-401 GET /auth/me failure while permissions are not yet ready.
   * Distinct from in-flight pending; not persisted.
   */
  identityError: string | null;
  /** True after local clear(); skips optimistic auth until setUser() runs. */
  signedOutLocally: boolean;
  setUser: (user: CurrentUser | null) => void;
  setIdentityError: (error: string) => void;
  clear: () => void;
};

function toDisplaySummary(user: CurrentUser): UserDisplaySummary {
  return {
    id: user.id,
    account: user.account,
    display_name: user.display_name,
    locale: user.locale,
    display_timezone: user.display_timezone,
  };
}

function userFromDisplaySummary(display: UserDisplaySummary): CurrentUser {
  return {
    id: display.id,
    account: display.account,
    display_name: display.display_name,
    email: null,
    locale: display.locale,
    display_timezone: display.display_timezone,
    role_id: null,
    role_key: null,
    role_name: null,
    permissions: [],
    identity_source: "local",
  };
}

function sessionStorageOrNoop() {
  if (typeof window === "undefined") {
    return {
      getItem: () => null,
      setItem: () => {},
      removeItem: () => {},
    };
  }
  return window.sessionStorage;
}

export const useSessionStore = create<SessionState>()(
  persist(
    (set) => ({
      user: null,
      permissionsReady: false,
      identityError: null,
      signedOutLocally: false,
      setUser: (user) =>
        set({
          user,
          permissionsReady: user !== null,
          identityError: null,
          signedOutLocally: false,
        }),
      setIdentityError: (error) => set({ identityError: error }),
      clear: () =>
        set({
          user: null,
          permissionsReady: false,
          identityError: null,
          signedOutLocally: true,
        }),
    }),
    {
      name: PERSIST_KEY,
      storage: createJSONStorage(() => sessionStorageOrNoop()),
      partialize: (state): PersistedSlice => ({
        display: state.user ? toDisplaySummary(state.user) : null,
      }),
      merge: (persisted, current) => {
        const slice = persisted as PersistedSlice | undefined;
        if (!slice?.display) {
          return current;
        }
        return {
          ...current,
          user: userFromDisplaySummary(slice.display),
          permissionsReady: false,
          identityError: null,
          signedOutLocally: false,
        };
      },
    },
  ),
);

export function getCurrentUser(): CurrentUser | null {
  return useSessionStore.getState().user;
}

export function isSignedOutLocally(): boolean {
  return useSessionStore.getState().signedOutLocally;
}

export function arePermissionsReady(): boolean {
  return useSessionStore.getState().permissionsReady;
}

/** Test helper: wipe memory + sessionStorage for this store. */
export function resetSessionStoreForTests() {
  useSessionStore.persist.clearStorage();
  useSessionStore.setState({
    user: null,
    permissionsReady: false,
    identityError: null,
    signedOutLocally: false,
  });
}
