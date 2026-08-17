import type { AuthActionResponse, AuthProvider } from "@refinedev/core";

import { useModuleIdentityStore } from "@/features/console/module-identity";
import { apiClient, ApiError } from "@/lib/api";
import { loginRedirectWithFrom } from "@/lib/return-path";
import { isProtectedPath } from "@/lib/route-scope";
import { translateKey } from "@/providers/i18n-runtime";
import {
  arePermissionsReady,
  getCurrentUser,
  isSignedOutLocally,
  useSessionStore,
  type CurrentUser,
} from "@/providers/session-store";

const IDENTITY_LOAD_FAILED = "identity_load_failed";
const IDENTITY_TIMEOUT_MS = 10_000;

function isProtectedDocument(): boolean {
  return typeof window !== "undefined" && isProtectedPath(window.location.pathname);
}

function clearClientSession() {
  useSessionStore.getState().clear();
  useModuleIdentityStore.getState().reset();
}

type LoginParams = { account: string; password: string };

type RefineAuth = AuthProvider & {
  login: (params: LoginParams) => Promise<AuthActionResponse>;
  logout: (params?: Record<string, unknown>) => Promise<AuthActionResponse>;
  check: () => Promise<{
    authenticated: boolean;
    redirectTo?: string;
    logout?: boolean;
  }>;
  getIdentity: () => Promise<CurrentUser | null>;
  getPermissions: () => Promise<string[]>;
  onError: (error: unknown) => Promise<{ redirectTo?: string; logout?: boolean }>;
};

async function fetchMe(): Promise<CurrentUser> {
  const data = await apiClient<{ user: CurrentUser }>("/auth/me", {
    timeoutMs: IDENTITY_TIMEOUT_MS,
  });
  useSessionStore.getState().setUser(data.user);
  return data.user;
}

function handleMeFailure(error: unknown): void {
  if (isApiError(error) && error.status === 401) {
    clearClientSession();
    if (typeof window !== "undefined" && isProtectedDocument()) {
      window.location.assign(loginRedirectWithFrom());
    }
    return;
  }
  if (arePermissionsReady()) {
    return;
  }
  useSessionStore.getState().setIdentityError(
    isApiError(error) ? error.detail : IDENTITY_LOAD_FAILED,
  );
}

/** Background Session revalidation; 401 clears UX snapshot and hard-navs to login. */
function revalidateSessionInBackground() {
  void fetchMe().catch(handleMeFailure);
}

/** Retry GET /auth/me after a non-401 identity load failure. */
export async function reloadIdentity(): Promise<void> {
  try {
    await fetchMe();
  } catch (error: unknown) {
    handleMeFailure(error);
  }
}

/** Outcome of a one-shot `/auth/me` probe on the public login page. */
export type LoginSessionProbe = "active" | "anonymous" | "load_error";

/**
 * Login-page Session probe; never hard-navigates.
 * 401 clears the display summary; non-401 is a load-error, not anonymity.
 */
export async function probeLoginSession(): Promise<LoginSessionProbe> {
  try {
    await fetchMe();
    return "active";
  } catch (error: unknown) {
    handleMeFailure(error);
    if (isApiError(error) && error.status === 401) {
      return "anonymous";
    }
    return "load_error";
  }
}

function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError;
}

function loginFailureError(error: unknown): AuthActionResponse["error"] {
  const name = translateKey("auth.login.title");
  if (!isApiError(error)) {
    return { name, message: translateKey("auth.login.error.network") };
  }
  if (error.status === 401) {
    return {
      name,
      message: translateKey("auth.login.error.invalidCredentials"),
      statusCode: error.status,
    };
  }
  if (error.status === 403) {
    const message =
      error.code === "AUTH_CONSOLE_ACCESS_REQUIRED"
        ? translateKey("auth.login.error.consoleAccess")
        : translateKey("auth.login.error.disabled");
    return {
      name,
      message,
      statusCode: error.status,
    };
  }
  return {
    name,
    message: error.detail,
    statusCode: error.status,
  };
}

function unauthenticatedCheckResponse() {
  return {
    authenticated: false as const,
    redirectTo: loginRedirectWithFrom(),
    logout: true as const,
  };
}

export const authProvider: RefineAuth = {
  async login(params: LoginParams): Promise<AuthActionResponse> {
    try {
      const data = await apiClient<{ user: CurrentUser }>("/auth/login", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(params),
      });
      useSessionStore.getState().setUser(data.user);
      // Omit redirectTo so Refine useLogin does not soft-navigate; LoginClient
      // performs a hard navigation after success.
      return { success: true };
    } catch (error) {
      clearClientSession();
      return {
        success: false,
        error: loginFailureError(error),
      };
    }
  },

  async logout(): Promise<AuthActionResponse> {
    try {
      await apiClient<{ success: boolean }>("/auth/logout", { method: "POST" });
    } catch (error) {
      if (isApiError(error) && error.status === 401) {
        clearClientSession();
        // Omit redirectTo; ConsoleShell hard-navigates after success.
        return { success: true };
      }
      return {
        success: false,
        error: isApiError(error)
          ? {
              name: error.code,
              message: error.detail,
              statusCode: error.status,
            }
          : new Error("logout failed"),
      };
    }
    clearClientSession();
    // Omit redirectTo so Refine useLogout does not soft-navigate; ConsoleShell
    // performs a hard navigation after success.
    return { success: true };
  },

  async check() {
    if (isSignedOutLocally()) {
      return unauthenticatedCheckResponse();
    }
    // Optimistic only on Console documents: proxy already gated on cookie
    // presence. Public pages stay anonymous and must not fetch /auth/me.
    if (isProtectedDocument()) {
      revalidateSessionInBackground();
    }
    return { authenticated: true };
  },

  async getIdentity() {
    const cached = getCurrentUser();
    if (cached) {
      return cached;
    }
    if (isSignedOutLocally() || !isProtectedDocument()) {
      return null;
    }
    try {
      return await fetchMe();
    } catch (error: unknown) {
      handleMeFailure(error);
      return null;
    }
  },

  async getPermissions() {
    if (isSignedOutLocally() || !isProtectedDocument()) {
      return [];
    }
    try {
      const identity = await fetchMe();
      return identity.permissions;
    } catch (error) {
      if (isApiError(error) && error.status === 401) {
        clearClientSession();
        return [];
      }
      handleMeFailure(error);
      return getCurrentUser()?.permissions ?? [];
    }
  },

  async onError(error) {
    if (isApiError(error)) {
      if (error.status === 401) {
        clearClientSession();
        return { redirectTo: loginRedirectWithFrom(), logout: true };
      }
      if (error.status === 403 && error.code === "AUTH_FORBIDDEN") {
        return { redirectTo: "/403" };
      }
    }
    return {};
  },
};
