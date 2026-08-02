import type { AuthActionResponse, AuthProvider } from "@refinedev/core";

import { apiClient, ApiError } from "@/lib/api";
import { loginRedirectWithFrom } from "@/lib/return-path";
import { i18n } from "@/providers/i18n";
import {
  getCurrentUser,
  isSignedOutLocally,
  useSessionStore,
  type CurrentUser,
} from "@/providers/session-store";

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
  const data = await apiClient<{ user: CurrentUser }>("/auth/me");
  useSessionStore.getState().setUser(data.user);
  return data.user;
}

function isApiError(value: unknown): value is ApiError {
  return value instanceof ApiError;
}

function loginFailureError(error: unknown): AuthActionResponse["error"] {
  const name = i18n.t("auth.login.title");
  if (!isApiError(error)) {
    return { name, message: i18n.t("auth.login.error.network") };
  }
  if (error.status === 401) {
    return {
      name,
      message: i18n.t("auth.login.error.invalidCredentials"),
      statusCode: error.status,
    };
  }
  if (error.status === 403) {
    const message =
      error.code === "AUTH_CONSOLE_ACCESS_REQUIRED"
        ? i18n.t("auth.login.error.consoleAccess")
        : i18n.t("auth.login.error.disabled");
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
      useSessionStore.getState().clear();
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
        useSessionStore.getState().clear();
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
    useSessionStore.getState().clear();
    // Omit redirectTo so Refine useLogout does not soft-navigate; ConsoleShell
    // performs a hard navigation after success.
    return { success: true };
  },

  async check() {
    if (isSignedOutLocally()) {
      return unauthenticatedCheckResponse();
    }
    try {
      await fetchMe();
      return { authenticated: true };
    } catch {
      useSessionStore.getState().clear();
      return unauthenticatedCheckResponse();
    }
  },

  async getIdentity() {
    const cached = getCurrentUser();
    if (cached) {
      return cached;
    }
    if (isSignedOutLocally()) {
      return null;
    }
    try {
      return await fetchMe();
    } catch {
      return null;
    }
  },

  async getPermissions() {
    if (isSignedOutLocally()) {
      return [];
    }
    try {
      const identity = await fetchMe();
      return identity.permissions;
    } catch (error) {
      if (isApiError(error) && error.status === 401) {
        useSessionStore.getState().clear();
        return [];
      }
      return getCurrentUser()?.permissions ?? [];
    }
  },

  async onError(error) {
    if (isApiError(error)) {
      if (error.status === 401) {
        useSessionStore.getState().clear();
        return { redirectTo: loginRedirectWithFrom(), logout: true };
      }
      if (error.status === 403 && error.code === "AUTH_FORBIDDEN") {
        return { redirectTo: "/403" };
      }
    }
    return {};
  },
};
