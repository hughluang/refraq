/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import { ConsoleNotifications } from "@/providers/notification-provider";
import {
  getUser,
  getUserGroups,
  getUserSourceAccess,
  getUserSubjectValues,
  listAllSubjectAttributes,
} from "@/features/subjects/api";

const USER_ID = "usr_0123456789ab";

const translate = vi.hoisted(
  () => (key: string) => {
    const dictionary: Record<string, string> = {
      "problems.unknown": "Something went wrong. Try again.",
      "common.retry": "Retry",
      "form.error.details": "Details",
      "common.requestId": "Request ID",
    };
    return dictionary[key] ?? key;
  },
);

const reload = vi.hoisted(() => vi.fn());

vi.mock("@refinedev/core", () => ({
  useTranslate: () => translate,
  useNotification: () => ({ open: vi.fn() }),
  useCan: () => ({ data: { can: false } }),
  useBreadcrumb: () => ({ breadcrumbs: [] }),
}));

vi.mock("@/features/branding/BrandingProvider", () => ({
  useBranding: () => ({ brandName: "Refraq" }),
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) =>
    createElement("a", { href }, children),
  useLinkStatus: () => ({ pending: false }),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => `/console/users/${USER_ID}`,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/providers/session-store", () => ({
  useSessionStore: (selector?: (state: { user: null }) => unknown) =>
    selector ? selector({ user: null }) : { user: null },
  getCurrentUser: () => null,
}));

vi.mock("@/providers/auth-provider", () => ({
  reloadIdentity: vi.fn(),
}));

vi.mock("@/features/subjects/api", () => ({
  getUser: vi.fn(),
  getUserGroups: vi.fn(),
  getUserSubjectValues: vi.fn(),
  listAllSubjectAttributes: vi.fn(),
  putUserGroups: vi.fn(),
  putUserSubjectValues: vi.fn(),
  getUserSourceAccess: vi.fn(),
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
  Object.defineProperty(window, "location", {
    configurable: true,
    value: { reload, pathname: `/console/users/${USER_ID}` },
  });
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

async function renderUser() {
  const { UserShow } = await import("@/features/users/UserShow");
  render(shell(createElement(UserShow, { userId: USER_ID })));
}

describe("User show load", () => {
  beforeEach(() => {
    stubDomApis();
    reload.mockClear();
    vi.mocked(getUser).mockClear();
    resetNotifications();
    vi.mocked(getUserGroups).mockResolvedValue({ groups: [] });
    vi.mocked(getUserSubjectValues).mockResolvedValue({ values: {}, effective: {} });
    vi.mocked(listAllSubjectAttributes).mockResolvedValue([]);
    vi.mocked(getUserSourceAccess).mockResolvedValue({ items: [] });
  });

  afterEach(() => {
    cleanup();
    resetNotifications();
  });

  it("keeps the header, shows unloaded, and retries the record load", async () => {
    vi.mocked(getUser).mockRejectedValue(
      new ApiError(500, "NO_SUCH_CODE", "Database unavailable", "req-17"),
    );
    await renderUser();

    expect(await screen.findByRole("heading", { name: "users.title" })).toBeTruthy();
    expect(await screen.findByRole("button", { name: "status.unloaded" })).toBeTruthy();
    expect(screen.queryByText("layout.notFound.title")).toBeNull();
    expect(screen.queryByText("common.error")).toBeNull();
    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    expect(screen.getByText("Something went wrong. Try again.")).toBeTruthy();
    fireEvent.click(screen.getByText("Details"));
    expect(screen.getByText("Database unavailable")).toBeTruthy();
    expect(screen.getByText("Request ID: req-17")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => {
      expect(getUser).toHaveBeenCalledTimes(2);
    });
    expect(getUser).toHaveBeenCalledWith(USER_ID);
    expect(reload).not.toHaveBeenCalled();

    fireEvent.click(await screen.findByRole("button", { name: "status.unloaded" }));
    await waitFor(() => {
      expect(getUser).toHaveBeenCalledTimes(3);
    });
    expect(reload).not.toHaveBeenCalled();
  });

  it("shows a network failure as unloaded, not as not-found", async () => {
    vi.mocked(getUser).mockRejectedValue(new Error("socket hang up"));
    await renderUser();

    expect(await screen.findByRole("button", { name: "status.unloaded" })).toBeTruthy();
    expect(screen.queryByText("layout.notFound.title")).toBeNull();
    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    expect(screen.queryByText("socket hang up")).toBeNull();
  });

  it("keeps a missing user on not-found", async () => {
    vi.mocked(getUser).mockResolvedValue({
      user: null as unknown as Awaited<ReturnType<typeof getUser>>["user"],
    });
    await renderUser();

    expect(await screen.findByText("layout.notFound.title")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "status.unloaded" })).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows an HTTP 404 as unloaded and retries the record load", async () => {
    vi.mocked(getUser).mockRejectedValue(
      new ApiError(404, "USER_NOT_FOUND", "User was not found", "req-404"),
    );
    await renderUser();

    expect(await screen.findByRole("heading", { name: "users.title" })).toBeTruthy();
    expect(await screen.findByRole("button", { name: "status.unloaded" })).toBeTruthy();
    expect(screen.queryByText("layout.notFound.title")).toBeNull();
    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    fireEvent.click(screen.getByText("Details"));
    expect(screen.getByText("Request ID: req-404")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => {
      expect(getUser).toHaveBeenCalledTimes(2);
    });
    expect(getUser).toHaveBeenCalledWith(USER_ID);
    expect(reload).not.toHaveBeenCalled();
  });
});
