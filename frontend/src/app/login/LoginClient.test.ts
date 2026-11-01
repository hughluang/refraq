/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { ConsoleNotifications } from "@/providers/notification-provider";

const signIn = vi.hoisted(() => vi.fn());
const probe = vi.hoisted(() => vi.fn());
const api = vi.hoisted(() => vi.fn());
const search = vi.hoisted(() => ({ params: new URLSearchParams() }));
const session = vi.hoisted(() => ({ identityError: null as string | null }));

vi.mock("@refinedev/core", () => {
  const known = new Set([
    "common.loading",
    "common.retry",
    "common.error.loadFailed",
    "common.requestId",
    "common.copy.success",
    "common.copy.failed",
    "auth.login.account",
    "auth.login.password",
    "auth.login.submit",
    "auth.login.ssoDivider",
    "auth.login.sso.pendingTitle",
    "auth.login.error.invalidCredentials",
    "auth.login.error.disabled",
    "auth.login.error.consoleAccess",
    "auth.login.error.network",
    "auth.login.error.sso",
    "auth.login.error.AUTH_SSO_NOT_ADMITTED",
    "auth.login.error.AUTH_SSO_PROVIDER_UNAVAILABLE",
    "auth.login.error.AUTH_SSO_HANDOFF_INVALID",
    "auth.login.error.AUTH_SSO_ASSERTION_REJECTED",
    "auth.login.error.AUTH_SESSION_EXPIRED",
    "auth.login.error.AUTH_ACCOUNT_DISABLED",
    "auth.login.error.AUTH_CONSOLE_ACCESS_REQUIRED",
    "problems.unknown",
    "form.error.details",
    "form.error.copy",
  ]);
  const translate = (key: string, options?: { defaultValue?: string }) => {
    if (key === "problems.CHANNEL_NOT_FOUND") return "Data Channel was not found";
    if (known.has(key)) return key;
    return options?.defaultValue ?? key;
  };
  return {
    useTranslate: () => translate,
  };
});

vi.mock("next/navigation", () => ({
  useSearchParams: () => search.params,
}));

vi.mock("@/features/branding/BrandingProvider", () => ({
  useBranding: () => ({
    logoUrl: null,
    brandName: "Refraq",
    tagline: null,
    raw: { show_brand_name_with_logo: true },
  }),
}));

vi.mock("@/providers/auth-provider", () => ({
  probeLoginSession: (...args: unknown[]) => probe(...args),
  signIn: (...args: unknown[]) => signIn(...args),
}));

vi.mock("@/providers/session-store", () => ({
  useSessionStore: (selector: (state: { identityError: string | null }) => unknown) =>
    selector({ identityError: session.identityError }),
}));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    apiClient: (...args: unknown[]) => api(...args),
  };
});

vi.mock("@/components/LangSwitcher", () => ({
  LangSwitcher: () => null,
}));

function stubDomApis() {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  });
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  globalThis.ResizeObserver = ResizeObserverStub;
}

function resetNotifications() {
  const state = notificationsStore.getState();
  for (const item of [...state.notifications, ...state.queue]) {
    notifications.hide(item.id);
  }
  notifications.clean();
}

function shell(node: ReactNode) {
  return createElement(
    MantineProvider,
    { env: "test" },
    createElement(ConsoleNotifications),
    node,
  );
}

function loginCard(): HTMLElement {
  const submit = screen.getByRole("button", { name: "auth.login.submit" });
  let node: HTMLElement | null = submit;
  while (node) {
    if (node.querySelector('a[href="https://github.com/hughluang/refraq"]')) return node;
    node = node.parentElement;
  }
  throw new Error("login card not found");
}

function notice(type: "warning" | "error", title: string): HTMLElement {
  const card = loginCard();
  expect(card.querySelector('[role="alert"]')).toBeNull();
  const alerts = screen.getAllByRole("alert").filter((item) => !card.contains(item));
  expect(alerts).toHaveLength(1);
  const alert = alerts[0];
  const icon = type === "warning" ? "tabler-icon-alert-triangle" : "tabler-icon-circle-x";
  expect(alert.querySelector(`.${icon}`)).toBeTruthy();
  const titleNode = [...alert.querySelectorAll("div")].find((item) => item.textContent === title);
  expect(titleNode).toBeTruthy();
  expect(titleNode?.closest("details")).toBeNull();
  return alert;
}

describe("login card failures", () => {
  beforeEach(() => {
    stubDomApis();
    signIn.mockReset();
    probe.mockReset();
    api.mockReset();
    search.params = new URLSearchParams();
    session.identityError = null;
    api.mockResolvedValue({ items: [] });
    signIn.mockResolvedValue(undefined);
    probe.mockResolvedValue({ status: "anonymous" });
    resetNotifications();
  });

  afterEach(() => {
    cleanup();
    resetNotifications();
  });

  it("shows a password failure as one error notification and keeps the card free of an alert", async () => {
    const { default: LoginPage } = await import("@/app/login/LoginClient");
    let settle: (value: { status: "anonymous" }) => void = () => {};
    probe.mockImplementation(
      () =>
        new Promise<{ status: "anonymous" }>((resolve) => {
          settle = resolve;
        }),
    );
    render(shell(createElement(LoginPage)));

    expect(screen.getByLabelText("common.loading").getAttribute("aria-busy")).toBe("true");
    expect(screen.queryByRole("button", { name: "auth.login.submit" })).toBeNull();

    settle({ status: "anonymous" });
    const submit = await screen.findByRole("button", { name: "auth.login.submit" });
    signIn.mockRejectedValue(
      new ApiError(401, "AUTH_INVALID_CREDENTIALS", "Raw English detail", "req-login-401"),
    );
    fireEvent.submit(submit.closest("form") as HTMLFormElement);

    const alert = await waitFor(() => notice("error", "auth.login.error.invalidCredentials"));
    expect(screen.getByText("Raw English detail").closest("details")).toBe(alert.querySelector("details"));
    expect(screen.getByText("common.requestId: req-login-401").closest("details")).toBeTruthy();
    expect(loginCard().textContent).not.toContain("auth.login.error.invalidCredentials");
    expect(loginCard().textContent).not.toContain("Raw English detail");
    expect(screen.getByRole("button", { name: "auth.login.submit" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "common.retry" })).toBeNull();
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    await waitFor(() => {
      expect(screen.queryByLabelText("common.loading")).toBeNull();
    });
  });

  it("presents a non-credential login failure as the problem sentence, not a bad password", async () => {
    const { default: LoginPage } = await import("@/app/login/LoginClient");
    render(shell(createElement(LoginPage)));
    const submit = await screen.findByRole("button", { name: "auth.login.submit" });
    signIn.mockRejectedValue(
      new ApiError(500, "NO_SUCH_CODE", "biztest-login-500", "req-login-500"),
    );
    fireEvent.submit(submit.closest("form") as HTMLFormElement);

    const alert = await waitFor(() => notice("error", "problems.unknown"));
    expect(screen.getByText("biztest-login-500").closest("details")).toBe(alert.querySelector("details"));
    expect(screen.getByText("common.requestId: req-login-500").closest("details")).toBeTruthy();
    expect(alert.textContent).not.toContain("auth.login.error.invalidCredentials");
    expect(screen.queryByText("auth.login.title")).toBeNull();
    expect(loginCard().textContent).not.toContain("biztest-login-500");
    expect(screen.getAllByRole("alert")).toHaveLength(1);
  });

  it("shows a waiting admission as one warning notification", async () => {
    search.params = new URLSearchParams("error=AUTH_SSO_NOT_ADMITTED");
    const { default: LoginPage } = await import("@/app/login/LoginClient");
    render(shell(createElement(LoginPage)));

    const submit = await screen.findByRole("button", { name: "auth.login.submit" });
    const alert = notice("warning", "auth.login.sso.pendingTitle");
    expect(alert.textContent).toContain("auth.login.error.AUTH_SSO_NOT_ADMITTED");
    const card = loginCard();
    expect(card.textContent).not.toContain("auth.login.sso.pendingTitle");
    expect(card.textContent).not.toContain("auth.login.error.AUTH_SSO_NOT_ADMITTED");
    expect(card.contains(submit)).toBe(true);
    expect(screen.queryByRole("button", { name: "common.retry" })).toBeNull();
  });

  it("shows another SSO failure as one error notification with that code's login copy", async () => {
    search.params = new URLSearchParams("error=AUTH_SSO_PROVIDER_UNAVAILABLE");
    const { default: LoginPage } = await import("@/app/login/LoginClient");
    render(shell(createElement(LoginPage)));

    await screen.findByRole("button", { name: "auth.login.submit" });
    const alert = notice("error", "auth.login.error.AUTH_SSO_PROVIDER_UNAVAILABLE");
    expect(loginCard().textContent).not.toContain("auth.login.error.AUTH_SSO_PROVIDER_UNAVAILABLE");
    expect(alert.textContent).not.toContain("auth.login.error.sso");
    expect(screen.queryByRole("button", { name: "common.retry" })).toBeNull();
  });

  it("falls back to the generic SSO error when the code has no login copy", async () => {
    search.params = new URLSearchParams("error=AUTH_NOT_A_REAL_CODE");
    const { default: LoginPage } = await import("@/app/login/LoginClient");
    render(shell(createElement(LoginPage)));

    await screen.findByRole("button", { name: "auth.login.submit" });
    notice("error", "auth.login.error.sso");
    expect(loginCard().textContent).not.toContain("auth.login.error.sso");
    expect(loginCard().textContent).not.toContain("AUTH_NOT_A_REAL_CODE");
  });

  it("shows an identity probe failure as one problem notification and retries the probe", async () => {
    probe.mockResolvedValue({
      status: "load_error",
      error: new ApiError(500, "CHANNEL_NOT_FOUND", "biztest-probe", "req_biztest_probe"),
    });
    const { default: LoginPage } = await import("@/app/login/LoginClient");
    render(shell(createElement(LoginPage)));

    const submit = await screen.findByRole("button", { name: "auth.login.submit" });
    const alert = await waitFor(() => notice("error", "Data Channel was not found"));
    expect(screen.getByText("biztest-probe").closest("details")).toBe(alert.querySelector("details"));
    expect(screen.getByText("common.requestId: req_biztest_probe").closest("details")).toBeTruthy();
    expect(loginCard().textContent).not.toContain("Data Channel was not found");
    expect(loginCard().textContent).not.toContain("biztest-probe");
    expect(loginCard().contains(submit)).toBe(true);
    const retry = screen.getByRole("button", { name: "common.retry" });
    expect(alert.contains(retry)).toBe(true);
    expect(loginCard().contains(retry)).toBe(false);

    fireEvent.click(retry);
    await waitFor(() => {
      expect(probe).toHaveBeenCalledTimes(2);
    });
  });

  it("shows a non-API identity probe failure as the load failure with retry", async () => {
    probe.mockResolvedValue({ status: "load_error", error: new Error("socket hang up") });
    const { default: LoginPage } = await import("@/app/login/LoginClient");
    render(shell(createElement(LoginPage)));

    await screen.findByRole("button", { name: "auth.login.submit" });
    const alert = await waitFor(() => notice("error", "common.error.loadFailed"));
    expect(screen.queryByText("socket hang up")).toBeNull();
    expect(alert.contains(screen.getByRole("button", { name: "common.retry" }))).toBe(true);
    expect(loginCard().textContent).not.toContain("common.error.loadFailed");
  });

  it("shows a provider list failure as one error notification and retries the load", async () => {
    api
      .mockRejectedValueOnce(
        new ApiError(500, "NO_SUCH_CODE", "Raw provider detail", "req-3"),
      )
      .mockResolvedValueOnce({
        items: [{ id: "okta", display_name: "Okta", protocol: "oidc" }],
      });
    const { default: LoginPage } = await import("@/app/login/LoginClient");
    render(shell(createElement(LoginPage)));

    await screen.findByRole("button", { name: "auth.login.submit" });
    const alert = await waitFor(() => notice("error", "problems.unknown"));
    expect(screen.getByText("Raw provider detail").closest("details")).toBeTruthy();
    expect(loginCard().textContent).not.toContain("Raw provider detail");
    expect(loginCard().textContent).not.toContain("problems.unknown");
    const retry = screen.getByRole("button", { name: "common.retry" });
    expect(alert.contains(retry)).toBe(true);
    expect(loginCard().contains(retry)).toBe(false);

    fireEvent.click(retry);
    expect(await screen.findByRole("link", { name: "Okta" })).toBeTruthy();
    expect(api).toHaveBeenCalledTimes(2);
  });

  it("shows a provider list network failure as the localized network error with retry", async () => {
    api.mockRejectedValue(new Error("socket hang up"));
    const { default: LoginPage } = await import("@/app/login/LoginClient");
    render(shell(createElement(LoginPage)));

    await screen.findByRole("button", { name: "auth.login.submit" });
    const alert = await waitFor(() => notice("error", "auth.login.error.network"));
    expect(screen.queryByText("socket hang up")).toBeNull();
    expect(loginCard().textContent).not.toContain("auth.login.error.network");
    const retry = screen.getByRole("button", { name: "common.retry" });
    expect(alert.contains(retry)).toBe(true);
    expect(loginCard().contains(retry)).toBe(false);

    api.mockResolvedValueOnce({
      items: [{ id: "okta", display_name: "Okta", protocol: "oidc" }],
    });
    fireEvent.click(retry);
    expect(await screen.findByRole("link", { name: "Okta" })).toBeTruthy();
  });
});
