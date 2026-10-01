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
  loginRedirectAfterSessionExpiry: () =>
    "/login?from=%2Fconsole&error=AUTH_SESSION_EXPIRED",
}));

import type { CurrentUser } from "@/providers/session-store";

type AuthModule = typeof import("@/providers/auth-provider");
type ApiModule = typeof import("@/lib/api");
type SessionModule = typeof import("@/providers/session-store");

let auth: AuthModule;
let api: ApiModule;
let session: SessionModule;

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
  beforeEach(async () => {
    vi.resetModules();
    api = await import("@/lib/api");
    auth = await import("@/providers/auth-provider");
    session = await import("@/providers/session-store");
    session.resetSessionStoreForTests();
    vi.mocked(api.apiClient).mockReset();
    vi.mocked(window.location.assign).mockReset();
    window.location.pathname = "/console";
    window.location.search = "";
  });

  afterEach(() => {
    session.resetSessionStoreForTests();
  });

  it("returns authenticated immediately without awaiting /auth/me", async () => {
    let resolveMe!: (value: { user: CurrentUser }) => void;
    vi.mocked(api.apiClient).mockImplementation(
      () =>
        new Promise((resolve) => {
          resolveMe = resolve;
        }),
    );

    const result = await auth.authProvider.check();
    expect(result).toEqual({ authenticated: true });
    expect(api.apiClient).toHaveBeenCalledWith("/auth/me", { timeoutMs: 10_000 });

    resolveMe({ user: sampleUser });
    await vi.waitFor(() => {
      expect(session.getCurrentUser()?.account).toBe("alice");
      expect(session.arePermissionsReady()).toBe(true);
    });
  });

  it("signedOutLocally skips optimistic auth and /auth/me", async () => {
    session.useSessionStore.getState().clear();
    const result = await auth.authProvider.check();
    expect(result.authenticated).toBe(false);
    expect(api.apiClient).not.toHaveBeenCalled();
  });

  it("401 from background revalidate clears store and hard-navigates", async () => {
    vi.mocked(api.apiClient).mockRejectedValue(
      new api.ApiError(401, "AUTH_UNAUTHENTICATED", "gone"),
    );

    await auth.authProvider.check();
    await vi.waitFor(() => {
      expect(session.isSignedOutLocally()).toBe(true);
      expect(session.getCurrentUser()).toBeNull();
      expect(window.location.assign).toHaveBeenCalledWith(
        "/login?from=%2Fconsole&error=AUTH_SESSION_EXPIRED",
      );
    });
  });

  it("non-401 /auth/me failure sets identityError and does not navigate", async () => {
    vi.mocked(api.apiClient).mockRejectedValue(
      new api.ApiError(500, "INTERNAL", "me unavailable"),
    );

    const result = await auth.authProvider.check();
    expect(result).toEqual({ authenticated: true });

    await vi.waitFor(() => {
      expect(session.useSessionStore.getState().identityError).toBe("me unavailable");
    });
    expect(session.arePermissionsReady()).toBe(false);
    expect(session.isSignedOutLocally()).toBe(false);
    expect(window.location.assign).not.toHaveBeenCalled();
  });

  it("non-401 /auth/me failure is ignored when permissions are already ready", async () => {
    session.useSessionStore.getState().setUser(sampleUser);
    vi.mocked(api.apiClient).mockRejectedValue(
      new api.ApiError(500, "INTERNAL", "me unavailable"),
    );

    await auth.authProvider.check();
    await new Promise((resolve) => setTimeout(resolve, 0));

    expect(session.useSessionStore.getState().identityError).toBeNull();
    expect(session.arePermissionsReady()).toBe(true);
    expect(window.location.assign).not.toHaveBeenCalled();
  });

  it("reloadIdentity clears identityError after a successful /auth/me", async () => {
    vi.mocked(api.apiClient).mockRejectedValueOnce(
      new api.ApiError(500, "INTERNAL", "me unavailable"),
    );
    await auth.authProvider.check();
    await vi.waitFor(() => {
      expect(session.useSessionStore.getState().identityError).toBe("me unavailable");
    });

    vi.mocked(api.apiClient).mockResolvedValueOnce({ user: sampleUser });
    await auth.reloadIdentity();
    expect(session.useSessionStore.getState().identityError).toBeNull();
    expect(session.arePermissionsReady()).toBe(true);
    expect(session.getCurrentUser()?.account).toBe("alice");
  });

  it("does not fetch or navigate when check/getIdentity run on /login", async () => {
    window.location.pathname = "/login";
    const check = await auth.authProvider.check();
    const identity = await auth.authProvider.getIdentity();
    const permissions = await auth.authProvider.getPermissions();

    expect(check).toEqual({ authenticated: true });
    expect(identity).toBeNull();
    expect(permissions).toEqual([]);
    expect(api.apiClient).not.toHaveBeenCalled();
    expect(window.location.assign).not.toHaveBeenCalled();
  });

  it("401 on /login clears the store without hard-navigating", async () => {
    window.location.pathname = "/login";
    vi.mocked(api.apiClient).mockRejectedValue(
      new api.ApiError(401, "AUTH_UNAUTHENTICATED", "gone"),
    );

    await auth.reloadIdentity();

    expect(session.isSignedOutLocally()).toBe(true);
    expect(session.getCurrentUser()).toBeNull();
    expect(window.location.assign).not.toHaveBeenCalled();
  });

  it("probeLoginSession is active after a successful /auth/me and never navigates", async () => {
    vi.mocked(api.apiClient).mockResolvedValue({ user: sampleUser });
    await expect(auth.probeLoginSession()).resolves.toBe("active");
    expect(session.getCurrentUser()?.account).toBe("alice");
    expect(window.location.assign).not.toHaveBeenCalled();
  });

  it("probeLoginSession is anonymous on 401, clears the store, and never navigates", async () => {
    window.location.pathname = "/login";
    session.useSessionStore.getState().setUser(sampleUser);
    vi.mocked(api.apiClient).mockRejectedValue(
      new api.ApiError(401, "AUTH_UNAUTHENTICATED", "gone"),
    );
    await expect(auth.probeLoginSession()).resolves.toBe("anonymous");
    expect(session.isSignedOutLocally()).toBe(true);
    expect(session.getCurrentUser()).toBeNull();
    expect(session.useSessionStore.getState().identityError).toBeNull();
    expect(window.location.assign).not.toHaveBeenCalled();
  });

  it("probeLoginSession is load_error on non-401, sets identityError, and never navigates", async () => {
    window.location.pathname = "/login";
    vi.mocked(api.apiClient).mockRejectedValue(
      new api.ApiError(500, "INTERNAL", "me unavailable"),
    );
    await expect(auth.probeLoginSession()).resolves.toBe("load_error");
    expect(session.useSessionStore.getState().identityError).toBe("me unavailable");
    expect(session.arePermissionsReady()).toBe(false);
    expect(session.isSignedOutLocally()).toBe(false);
    expect(window.location.assign).not.toHaveBeenCalled();
  });
});
