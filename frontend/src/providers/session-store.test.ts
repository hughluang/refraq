import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const memory = vi.hoisted(() => {
  const store = new Map<string, string>();
  vi.stubGlobal("window", {
    sessionStorage: {
      getItem: (key: string) => store.get(key) ?? null,
      setItem: (key: string, value: string) => {
        store.set(key, value);
      },
      removeItem: (key: string) => {
        store.delete(key);
      },
    },
  });
  return store;
});

import {
  arePermissionsReady,
  getCurrentUser,
  isSignedOutLocally,
  resetSessionStoreForTests,
  useSessionStore,
  type CurrentUser,
} from "@/providers/session-store";

const sampleUser: CurrentUser = {
  id: "u1",
  account: "alice",
  display_name: "Alice",
  email: "alice@example.com",
  locale: "en",
  display_timezone: "Asia/Shanghai",
  role_id: "r1",
  role_key: "operator",
  role_name: "Operator",
  permissions: ["console:access", "jobs:run"],
  identity_source: "local",
};

describe("session-store persist", () => {
  beforeEach(() => {
    memory.clear();
    resetSessionStoreForTests();
  });

  afterEach(() => {
    memory.clear();
    resetSessionStoreForTests();
  });

  it("persists only the display summary, not permissions or email", () => {
    useSessionStore.getState().setUser(sampleUser);
    expect(arePermissionsReady()).toBe(true);

    const raw = memory.get("refraq.console.user-display");
    expect(raw).toBeTruthy();
    const parsed = JSON.parse(raw!) as {
      state: { display: Record<string, unknown> };
    };
    expect(parsed.state.display).toEqual({
      id: "u1",
      account: "alice",
      display_name: "Alice",
      locale: "en",
      display_timezone: "Asia/Shanghai",
    });
    expect(parsed.state.display).not.toHaveProperty("permissions");
    expect(parsed.state.display).not.toHaveProperty("email");
    expect(parsed.state.display).not.toHaveProperty("role_key");
  });

  it("clear() wipes storage before hard navigation can race", () => {
    useSessionStore.getState().setUser(sampleUser);
    useSessionStore.getState().clear();

    expect(getCurrentUser()).toBeNull();
    expect(arePermissionsReady()).toBe(false);
    expect(isSignedOutLocally()).toBe(true);

    const raw = memory.get("refraq.console.user-display");
    if (raw) {
      const parsed = JSON.parse(raw) as {
        state: { display: unknown };
      };
      expect(parsed.state.display).toBeNull();
    }
  });

  it("restores display summary without marking permissions ready", async () => {
    useSessionStore.getState().setUser(sampleUser);
    const raw = memory.get("refraq.console.user-display");
    expect(raw).toBeTruthy();

    resetSessionStoreForTests();
    memory.set("refraq.console.user-display", raw!);

    await useSessionStore.persist.rehydrate();

    const user = getCurrentUser();
    expect(user?.account).toBe("alice");
    expect(user?.display_timezone).toBe("Asia/Shanghai");
    expect(user?.permissions).toEqual([]);
    expect(user?.email).toBeNull();
    expect(arePermissionsReady()).toBe(false);
    expect(isSignedOutLocally()).toBe(false);
    expect(user?.display_name).toBe("Alice");
    expect(useSessionStore.getState().identityError).toBeNull();
  });

  it("does not persist identityError; setUser clears it", () => {
    useSessionStore.getState().setUser(sampleUser);
    useSessionStore.getState().setIdentityError("me failed");
    expect(useSessionStore.getState().identityError).toBe("me failed");

    const raw = memory.get("refraq.console.user-display");
    expect(raw).toBeTruthy();
    const parsed = JSON.parse(raw!) as {
      state: Record<string, unknown>;
    };
    expect(parsed.state).not.toHaveProperty("identityError");
    expect(parsed.state).toHaveProperty("display");

    useSessionStore.getState().setUser(sampleUser);
    expect(useSessionStore.getState().identityError).toBeNull();
    expect(arePermissionsReady()).toBe(true);
  });
});
