import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.hoisted(() => {
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
    location: { assign: vi.fn(), pathname: "/console", search: "" },
  });
});

vi.mock("@/lib/api", () => ({
  ApiError: class ApiError extends Error {
    status: number;
    code: string;
    detail: string;
    constructor(status: number, code: string, detail: string) {
      super(detail);
      this.status = status;
      this.code = code;
      this.detail = detail;
    }
  },
  apiClient: vi.fn(),
}));

vi.mock("@/features/console/module-identity", () => ({
  useModuleIdentityStore: {
    getState: () => ({ reset: vi.fn() }),
  },
}));

vi.mock("@/providers/i18n-runtime", () => ({
  translateKey: (key: string) => key,
}));

vi.mock("@/lib/return-path", () => ({
  loginRedirectWithFrom: () => "/login?from=%2Fconsole",
}));

import { ApiError, apiClient } from "@/lib/api";
import {
  authProvider,
  probeLoginSession,
  reloadIdentity,
} from "@/providers/auth-provider";
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
  email: null,
  locale: "en",
  display_timezone: null,
  role_id: null,
  role_key: null,
  role_name: null,
  permissions: ["console:access"],
  identity_source: "local",
};

describe("authProvider.check optimistic", () => {
  beforeEach(() => {
    resetSessionStoreForTests();
    vi.mocked(apiClient).mockReset();
    vi.mocked(window.location.assign).mockReset();
    window.location.pathname = "/console";
    window.location.search = "";
  });

  afterEach(() => {
    resetSessionStoreForTests();
  });

  it("returns authenticated immediately without awaiting /auth/me", async () => {
    let resolveMe!: (value: { user: CurrentUser }) => void;
    vi.mocked(apiClient).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveMe = resolve;
        }),
    );

    const result = await authProvider.check();
    expect(result).toEqual({ authenticated: true });
    expect(apiClient).toHaveBeenCalledWith("/auth/me", { timeoutMs: 10_000 });

    resolveMe({ user: sampleUser });
    await vi.waitFor(() => {
      expect(getCurrentUser()?.account).toBe("alice");
      expect(arePermissionsReady()).toBe(true);
    });
  });

  it("signedOutLocally skips optimistic auth and /auth/me", async () => {
    useSessionStore.getState().clear();
    const result = await authProvider.check();
    expect(result.authenticated).toBe(false);
    expect(apiClient).not.toHaveBeenCalled();
  });

  it("401 from background revalidate clears store and hard-navigates", async () => {
    vi.mocked(apiClient).mockRejectedValue(
      new ApiError(401, "AUTH_UNAUTHENTICATED", "gone"),
    );

    await authProvider.check();
    await vi.waitFor(() => {
      expect(isSignedOutLocally()).toBe(true);
      expect(getCurrentUser()).toBeNull();
      expect(window.location.assign).toHaveBeenCalledWith(
        "/login?from=%2Fconsole",
      );
    });
  });

  it("non-401 /auth/me failure sets identityError and does not navigate", async () => {
    vi.mocked(apiClient).mockRejectedValue(
      new ApiError(500, "INTERNAL", "me unavailable"),
    );

    const result = await authProvider.check();
    expect(result).toEqual({ authenticated: true });

    await vi.waitFor(() => {
      expect(useSessionStore.getState().identityError).toBe("me unavailable");
    });
    expect(arePermissionsReady()).toBe(false);
    expect(isSignedOutLocally()).toBe(false);
    expect(window.location.assign).not.toHaveBeenCalled();
  });

  it("non-401 /auth/me failure is ignored when permissions are already ready", async () => {
    useSessionStore.getState().setUser(sampleUser);
    vi.mocked(apiClient).mockRejectedValue(
      new ApiError(500, "INTERNAL", "me unavailable"),
    );

    await authProvider.check();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(useSessionStore.getState().identityError).toBeNull();
    expect(arePermissionsReady()).toBe(true);
    expect(window.location.assign).not.toHaveBeenCalled();
  });

  it("reloadIdentity clears identityError after a successful /auth/me", async () => {
    vi.mocked(apiClient).mockRejectedValueOnce(
      new ApiError(500, "INTERNAL", "me unavailable"),
    );
    await authProvider.check();
    await vi.waitFor(() => {
      expect(useSessionStore.getState().identityError).toBe("me unavailable");
    });

    vi.mocked(apiClient).mockResolvedValueOnce({ user: sampleUser });
    await reloadIdentity();
    expect(useSessionStore.getState().identityError).toBeNull();
    expect(arePermissionsReady()).toBe(true);
    expect(getCurrentUser()?.account).toBe("alice");
  });

  it("does not fetch or navigate when check/getIdentity run on /login", async () => {
    window.location.pathname = "/login";
    const check = await authProvider.check();
    const identity = await authProvider.getIdentity();
    const permissions = await authProvider.getPermissions();

    expect(check).toEqual({ authenticated: true });
    expect(identity).toBeNull();
    expect(permissions).toEqual([]);
    expect(apiClient).not.toHaveBeenCalled();
    expect(window.location.assign).not.toHaveBeenCalled();
  });

  it("401 on /login clears the store without hard-navigating", async () => {
    window.location.pathname = "/login";
    vi.mocked(apiClient).mockRejectedValue(
      new ApiError(401, "AUTH_UNAUTHENTICATED", "gone"),
    );

    await reloadIdentity();

    expect(isSignedOutLocally()).toBe(true);
    expect(getCurrentUser()).toBeNull();
    expect(window.location.assign).not.toHaveBeenCalled();
  });

  it("probeLoginSession is active after a successful /auth/me and never navigates", async () => {
    vi.mocked(apiClient).mockResolvedValue({ user: sampleUser });
    await expect(probeLoginSession()).resolves.toBe("active");
    expect(getCurrentUser()?.account).toBe("alice");
    expect(window.location.assign).not.toHaveBeenCalled();
  });

  it("probeLoginSession is anonymous on 401, clears the store, and never navigates", async () => {
    window.location.pathname = "/login";
    useSessionStore.getState().setUser(sampleUser);
    vi.mocked(apiClient).mockRejectedValue(
      new ApiError(401, "AUTH_UNAUTHENTICATED", "gone"),
    );
    await expect(probeLoginSession()).resolves.toBe("anonymous");
    expect(isSignedOutLocally()).toBe(true);
    expect(getCurrentUser()).toBeNull();
    expect(useSessionStore.getState().identityError).toBeNull();
    expect(window.location.assign).not.toHaveBeenCalled();
  });

  it("probeLoginSession is load_error on non-401, sets identityError, and never navigates", async () => {
    window.location.pathname = "/login";
    vi.mocked(apiClient).mockRejectedValue(
      new ApiError(500, "INTERNAL", "me unavailable"),
    );
    await expect(probeLoginSession()).resolves.toBe("load_error");
    expect(useSessionStore.getState().identityError).toBe("me unavailable");
    expect(arePermissionsReady()).toBe(false);
    expect(isSignedOutLocally()).toBe(false);
    expect(window.location.assign).not.toHaveBeenCalled();
  });
});
