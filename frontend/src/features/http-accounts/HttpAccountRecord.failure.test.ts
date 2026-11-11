/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import type { HttpAccount } from "@/features/http-accounts/types";
import { ConsoleNotifications } from "@/providers/notification-provider";

const getHttpAccount = vi.hoisted(() => vi.fn());
const createHttpAccount = vi.hoisted(() => vi.fn());
const patchHttpAccount = vi.hoisted(() => vi.fn());

vi.mock("@refinedev/core", () => ({
  matchResourceFromRoute: () => ({ found: false }),
  useTranslate: () => (key: string) => key,
  useCan: () => ({ data: { can: true } }),
  useNotification: () => ({ open: vi.fn() }),
  useBreadcrumb: () => ({ breadcrumbs: [] }),
}));

vi.mock("@/features/http-accounts/api", () => ({
  getHttpAccount,
  createHttpAccount,
  patchHttpAccount,
  deleteHttpAccount: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children?: ReactNode }) =>
    createElement("a", { href }, children),
  useLinkStatus: () => ({ pending: false }),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/console/http-accounts/hac_1",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/features/branding/BrandingProvider", () => ({
  useBranding: () => ({ brandName: "Refraq" }),
}));

vi.mock("@/providers/session-store", () => ({
  useSessionStore: (selector: (state: { user: null }) => unknown) =>
    selector({ user: null }),
}));

const ACCOUNT: HttpAccount = {
  id: "hac_bb2e851a5eb1",
  name: "Office",
  auth: { type: "bearer" },
  headers: [],
  query: [],
  allowed_origins: [],
  created_at: "2026-10-29T00:00:00Z",
  updated_at: "2026-10-29T00:00:00Z",
};

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

function rejected(requestId: string) {
  return new ApiError(500, "NO_SUCH_CODE", "Raw English detail", requestId);
}

describe("HttpAccountRecord failures", () => {
  beforeEach(() => {
    stubDomApis();
    getHttpAccount.mockReset();
    createHttpAccount.mockReset();
    patchHttpAccount.mockReset();
    resetNotifications();
  });

  afterEach(() => {
    cleanup();
    resetNotifications();
  });

  it("keeps the header, shows unloaded, and notifies once with retry and the request id", async () => {
    getHttpAccount.mockRejectedValueOnce(rejected("req-load"));
    getHttpAccount.mockResolvedValueOnce({ http_account: ACCOUNT });
    const { HttpAccountRecord } = await import("@/features/http-accounts/HttpAccountRecord");
    render(
      shell(createElement(HttpAccountRecord, { mode: "show", accountId: ACCOUNT.id })),
    );

    const heading = await screen.findByRole("heading", { name: "httpAccounts.title" });
    expect(document.querySelector("[data-page-header]")?.contains(heading)).toBe(true);
    const status = screen.getByRole("button", { name: "status.unloaded" });
    const scroll = document.querySelector("[data-page-scroll]");
    expect(scroll?.contains(status)).toBe(true);
    expect(scroll?.querySelector("[role='alert']")).toBeNull();
    expect(scroll?.textContent).not.toContain("req-load");
    expect(screen.queryByText("common.error")).toBeNull();
    const alerts = screen.getAllByRole("alert");
    expect(alerts).toHaveLength(1);
    expect(alerts[0].textContent).toContain("problems.unknown");
    expect(alerts[0].textContent).toContain("common.requestId");
    expect(alerts[0].textContent).toContain("req-load");

    fireEvent.click(screen.getByRole("button", { name: "common.retry" }));
    expect(await screen.findByRole("heading", { name: "Office" })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "status.unloaded" })).toBeNull();
    expect(getHttpAccount).toHaveBeenCalledTimes(2);
    expect(getHttpAccount).toHaveBeenNthCalledWith(1, ACCOUNT.id);
    expect(getHttpAccount).toHaveBeenNthCalledWith(2, ACCOUNT.id);
  });

  it("shows one error notification and no form alert when create is rejected", async () => {
    createHttpAccount.mockRejectedValue(rejected("req-create"));
    const { HttpAccountRecord } = await import("@/features/http-accounts/HttpAccountRecord");
    render(shell(createElement(HttpAccountRecord, { mode: "create" })));
    fireEvent.change(screen.getByLabelText("httpAccounts.fields.name"), {
      target: { value: "Office" },
    });
    fireEvent.submit(document.getElementById("http-account-record-form") as HTMLFormElement);

    const alerts = await screen.findAllByRole("alert");
    expect(alerts).toHaveLength(1);
    const form = document.getElementById("http-account-record-form");
    expect(form?.querySelector("[role='alert']")).toBeNull();
    expect(alerts[0].textContent).toContain("problems.unknown");
    expect(alerts[0].textContent).toContain("common.requestId");
    expect(alerts[0].textContent).toContain("req-create");
    expect(screen.queryByRole("button", { name: "common.retry" })).toBeNull();
  });

  it("shows one error notification and no form alert when the edit save is rejected", async () => {
    getHttpAccount.mockResolvedValue({ http_account: ACCOUNT });
    patchHttpAccount.mockRejectedValue(rejected("req-edit"));
    const { HttpAccountRecord } = await import("@/features/http-accounts/HttpAccountRecord");
    render(
      shell(createElement(HttpAccountRecord, { mode: "edit", accountId: ACCOUNT.id })),
    );
    expect(await screen.findByDisplayValue("Office")).toBeTruthy();
    fireEvent.submit(document.getElementById("http-account-record-form") as HTMLFormElement);

    const alerts = await screen.findAllByRole("alert");
    expect(alerts).toHaveLength(1);
    const form = document.getElementById("http-account-record-form");
    expect(form?.querySelector("[role='alert']")).toBeNull();
    expect(alerts[0].textContent).toContain("req-edit");
    expect(screen.queryByRole("button", { name: "common.retry" })).toBeNull();
  });
});
