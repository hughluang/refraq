/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import en from "@/locales/en-US/common.json";
import { ConsoleNotifications } from "@/providers/notification-provider";
import type { PendingFederatedIdentity } from "@/features/identity-providers/types";
import type { RoleRow } from "@/features/roles/types";

const messages = en as Record<string, string>;

const usersApi = vi.hoisted(() => ({
  list: vi.fn(),
}));

const federationApi = vi.hoisted(() => ({
  listPending: vi.fn(),
  claim: vi.fn(),
  unfederate: vi.fn(),
}));

const rolesApi = vi.hoisted(() => ({
  list: vi.fn(),
  get: vi.fn(),
}));

function translate(key: string, options?: Record<string, unknown>) {
  const template = messages[key] ?? key;
  if (!options) return template;
  return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) =>
    String(options[name] ?? ""),
  );
}

vi.mock("@refinedev/core", () => ({
  useTranslate: () => translate,
  useNotification: () => ({ open: vi.fn() }),
  useGetIdentity: () => ({ data: { id: "self-user" } }),
  useCan: () => ({ data: { can: true } }),
  useUpdate: () => ({ mutate: vi.fn() }),
  CanAccess: ({ children }: { children?: ReactNode }) => children,
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/console/users",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/features/users/api", () => ({
  listUsers: (...args: unknown[]) => usersApi.list(...args),
}));

vi.mock("@/features/identity-providers/api", () => ({
  listPendingFederatedIdentities: (...args: unknown[]) => federationApi.listPending(...args),
  claimPendingFederatedIdentity: (...args: unknown[]) => federationApi.claim(...args),
  unfederateUser: (...args: unknown[]) => federationApi.unfederate(...args),
}));

vi.mock("@/features/roles/api", () => ({
  listRoles: (...args: unknown[]) => rolesApi.list(...args),
  getRole: (...args: unknown[]) => rolesApi.get(...args),
}));

vi.mock("@/components/layout/PageChrome", () => ({
  PageChrome: ({
    children,
    tabs,
    actions,
    toolbar,
  }: {
    children?: ReactNode;
    tabs?: ReactNode;
    actions?: ReactNode;
    toolbar?: ReactNode;
  }) => createElement("div", null, actions, toolbar, tabs, children),
}));

vi.mock("@/components/navigation/ConsoleLink", () => ({
  ConsoleLink: ({ children }: { children?: ReactNode }) =>
    createElement("a", null, children),
}));

const PENDING: PendingFederatedIdentity = {
  id: "pfi-1",
  issuer: "https://idp.example",
  account_hint: "ada",
  display_name: "Ada Lovelace",
  email: "ada@example.com",
  groups: [],
  admission_reason: "auto_disabled",
  attempt_count: 1,
  first_seen_at: "2026-10-01T00:00:00Z",
  last_attempt_at: "2026-10-01T00:00:00Z",
  expires_at: "2026-11-01T00:00:00Z",
  subject: "sub-1",
  provider_id: null,
};

const ANALYST: RoleRow = {
  id: "role-1",
  key: "analyst",
  name: "Analyst",
  permissions: [],
  locked: false,
  user_count: 1,
};

function emptyPage() {
  return { items: [], total: 0, limit: 50, offset: 0 };
}

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
  if (document.fonts == null) {
    Object.defineProperty(document, "fonts", {
      configurable: true,
      value: { addEventListener() {}, removeEventListener() {} },
    });
  }
  HTMLElement.prototype.scrollIntoView = () => {};
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

async function openClaimAndSubmit() {
  fireEvent.click(screen.getByRole("tab", { name: /Pending federated identities/ }));
  fireEvent.click(await screen.findByRole("button", { name: "Claim" }));
  const dialog = await screen.findByRole("dialog");
  fireEvent.click(within(dialog).getByLabelText(/^Role/));
  fireEvent.click(await screen.findByRole("option", { name: /Analyst/ }));
  fireEvent.click(within(dialog).getByRole("button", { name: "Claim" }));
  return dialog;
}

describe("UserList claim dialog", () => {
  beforeEach(() => {
    stubDomApis();
    usersApi.list.mockReset();
    federationApi.listPending.mockReset();
    federationApi.claim.mockReset();
    federationApi.unfederate.mockReset();
    rolesApi.list.mockReset();
    rolesApi.get.mockReset();
    usersApi.list.mockResolvedValue(emptyPage());
    federationApi.listPending.mockResolvedValue({
      items: [PENDING],
      total: 1,
      limit: 50,
      offset: 0,
    });
    rolesApi.list.mockResolvedValue({
      items: [ANALYST],
      total: 1,
      limit: 20,
      offset: 0,
    });
    resetNotifications();
  });

  afterEach(() => {
    cleanup();
    resetNotifications();
  });

  it("shows one error notification and no save alert when the claim is rejected", async () => {
    federationApi.claim.mockRejectedValue(
      new ApiError(500, "NO_SUCH_CODE", "Raw English detail", "req-claim"),
    );
    const { UserList } = await import("@/features/users/UserList");
    render(shell(createElement(UserList)));
    const dialog = await openClaimAndSubmit();

    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    expect(dialog.querySelector("[role='alert']")).toBeNull();
    const title = screen.getByText(messages["problems.unknown"]);
    expect(title.closest("details")).toBeNull();
    fireEvent.click(screen.getByText(messages["form.error.details"]));
    expect(screen.getByText("Raw English detail").closest("details")).toBeTruthy();
    expect(dialog.textContent).not.toContain("Raw English detail");
  });

  it("marks the account field and sends no notification when every detail maps", async () => {
    federationApi.claim.mockRejectedValue(
      new ApiError(422, "REQUEST_INVALID", "Request validation failed", "req-full", {}, [
        { field: "account", message: "Account is taken" },
      ]),
    );
    const { UserList } = await import("@/features/users/UserList");
    render(shell(createElement(UserList)));
    const dialog = await openClaimAndSubmit();

    expect(await screen.findByText("Account is taken")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(dialog.querySelector("[role='alert']")).toBeNull();
    expect(screen.queryByText(messages["form.error.details"])).toBeNull();
  });

  it("marks the mapped field and discloses only the unmapped detail", async () => {
    federationApi.claim.mockRejectedValue(
      new ApiError(422, "REQUEST_INVALID", "Request validation failed", "req-part", {}, [
        { field: "account", message: "Account is taken" },
        { field: "retired", message: "Unknown field" },
      ]),
    );
    const { UserList } = await import("@/features/users/UserList");
    render(shell(createElement(UserList)));
    const dialog = await openClaimAndSubmit();

    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    expect(dialog.querySelector("[role='alert']")).toBeNull();
    expect(screen.getByText("Account is taken")).toBeTruthy();
    fireEvent.click(screen.getByText(messages["form.error.details"]));
    const disclosure = screen.getByText(messages["form.error.details"]).closest("details");
    expect(disclosure?.textContent).toContain("retired: Unknown field");
    expect(disclosure?.textContent).not.toContain("Account is taken");
    expect(dialog.textContent).not.toContain("Unknown field");
  });
});
