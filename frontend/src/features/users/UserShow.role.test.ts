/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en-US/common.json";
import type { RoleRow } from "@/features/roles/types";
import type { UserRow } from "@/features/users/types";
import { ApiError } from "@/lib/api";

const copy = en as Record<string, string>;
const translate = (key: string) => copy[key] ?? key;
const USER_ID = "usr_ada";
const canWrite = vi.hoisted(() => ({ value: true }));
const getUser = vi.hoisted(() => vi.fn());
const updateUserRole = vi.hoisted(() => vi.fn());
const listRoles = vi.hoisted(() => vi.fn());
const reloadIdentity = vi.hoisted(() => vi.fn());
const notify = vi.hoisted(() => vi.fn());
const sessionUser = vi.hoisted(() => ({ id: null as string | null }));

vi.mock("@refinedev/core", () => ({
  matchResourceFromRoute: () => ({ found: false }),
  useTranslate: () => translate,
  useNotification: () => ({ open: notify }),
  useCan: () => ({ data: { can: canWrite.value } }),
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
  useSessionStore: (selector?: (state: { user: { id: string } | null }) => unknown) =>
    selector ? selector({ user: sessionUser.id ? { id: sessionUser.id } : null }) : { user: null },
  getCurrentUser: () =>
    sessionUser.id
      ? { id: sessionUser.id, permissions: ["console:access", "users:write"] }
      : null,
}));

vi.mock("@/providers/auth-provider", () => ({
  reloadIdentity: () => reloadIdentity(),
}));

vi.mock("@/features/subjects/api", () => ({
  getUser: (...args: unknown[]) => getUser(...args),
  getUserGroups: vi.fn().mockResolvedValue({ groups: [] }),
  getUserSubjectValues: vi.fn().mockResolvedValue({ values: {}, effective: {} }),
  listAllSubjectAttributes: vi.fn().mockResolvedValue([]),
  putUserGroups: vi.fn(),
  putUserSubjectValues: vi.fn(),
  getUserSourceAccess: vi.fn().mockResolvedValue({ items: [] }),
}));

vi.mock("@/features/users/api", () => ({
  updateUserRole: (...args: unknown[]) => updateUserRole(...args),
}));

vi.mock("@/features/roles/api", () => ({
  listRoles: (...args: unknown[]) => listRoles(...args),
  getRole: vi.fn(),
}));

function user(role: Partial<UserRow> = {}): UserRow {
  return {
    id: USER_ID,
    account: "ada",
    display_name: "Ada",
    email: null,
    locale: "en-US",
    display_timezone: null,
    role_id: "role_1",
    role_key: "analyst",
    role_name: "Analyst",
    status: "active",
    identity_source: "local",
    last_login_at: null,
    ...role,
  };
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
}

function shell(node: ReactNode) {
  return createElement(MantineProvider, { env: "test" }, node);
}

async function renderUser() {
  const { UserShow } = await import("@/features/users/UserShow");
  render(shell(createElement(UserShow, { userId: USER_ID })));
}

function operatorRole(): RoleRow {
  return {
    id: "role_2",
    key: "operator",
    name: "Operator",
    permissions: [],
    locked: false,
    user_count: 0,
  };
}

function roleControl(): HTMLElement {
  const label = screen.getByText(copy["users.fields.role"]);
  const control = label.closest(".field-chrome")?.querySelector("button");
  if (!control) throw new Error("role control missing");
  return control;
}

async function chooseOperator() {
  listRoles.mockResolvedValue({
    items: [operatorRole()],
    total: 1,
    limit: 20,
    offset: 0,
  });
  const current = await screen.findByText("Analyst");
  const trigger = current.closest("button");
  if (!trigger) throw new Error("role control missing");
  fireEvent.click(trigger);
  fireEvent.click(await screen.findByRole("option", { name: /Operator/ }));
  await waitFor(() => {
    expect(roleControl().textContent).toContain("Operator");
  });
}

describe("User role binding", () => {
  beforeEach(() => {
    stubDomApis();
    canWrite.value = true;
    sessionUser.id = null;
    notify.mockClear();
    reloadIdentity.mockReset();
    reloadIdentity.mockResolvedValue(undefined);
    updateUserRole.mockReset();
    listRoles.mockReset();
    listRoles.mockResolvedValue({ items: [], total: 0, limit: 20, offset: 0 });
    getUser.mockResolvedValue({ user: user() });
  });

  afterEach(() => {
    cleanup();
  });

  it("shows the current role and saves a replacement", async () => {
    const saved = user({
      role_id: "role_2",
      role_key: "operator",
      role_name: "Operator",
    });
    updateUserRole.mockResolvedValue({ user: saved });
    await renderUser();

    expect(await screen.findByText("Analyst")).toBeTruthy();
    expect(screen.getByText(copy["users.fields.role.help"])).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: copy["users.role.save"] }));

    expect(updateUserRole).toHaveBeenCalledWith(USER_ID, "role_1");
    expect(await screen.findByText("Operator")).toBeTruthy();
    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({ type: "success", description: copy["users.role.saved"] }),
    );
    expect(reloadIdentity).not.toHaveBeenCalled();
  });

  it("saves a cleared role", async () => {
    getUser.mockResolvedValue({ user: user({ role_id: null, role_key: null, role_name: null }) });
    updateUserRole.mockResolvedValue({
      user: user({ role_id: null, role_key: null, role_name: null }),
    });
    await renderUser();

    expect(await screen.findByText(copy["users.roles.none"])).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: copy["users.role.save"] }));
    expect(updateUserRole).toHaveBeenCalledWith(USER_ID, null);
  });

  it("restores the loaded role when the save is refused", async () => {
    updateUserRole.mockRejectedValue(
      new ApiError(
        409,
        "USER_LAST_LOCAL_SUPER_ADMIN",
        "The last active local super admin cannot leave that role",
        "req-last",
      ),
    );
    await renderUser();
    await chooseOperator();

    fireEvent.click(screen.getByRole("button", { name: copy["users.role.save"] }));

    expect(updateUserRole).toHaveBeenCalledWith(USER_ID, "role_2");
    await waitFor(() => {
      expect(roleControl().textContent).toContain("Analyst");
    });
    expect(roleControl().textContent).not.toContain("Operator");
    expect(notify).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "error",
        message: copy["users.title"],
        description: copy["problems.USER_LAST_LOCAL_SUPER_ADMIN"],
      }),
    );
  });

  it("keeps the selected role when the save fails without a response", async () => {
    updateUserRole.mockRejectedValue(new Error("network down"));
    await renderUser();
    await chooseOperator();

    fireEvent.click(screen.getByRole("button", { name: copy["users.role.save"] }));

    await waitFor(() => {
      expect(notify).toHaveBeenCalledWith(
        expect.objectContaining({
          type: "error",
          message: copy["users.title"],
          description: copy["common.error.loadFailed"],
        }),
      );
    });
    expect(roleControl().textContent).toContain("Operator");
    expect(roleControl().textContent).not.toContain("Analyst");
  });

  it("hides save when the actor cannot write users", async () => {
    canWrite.value = false;
    await renderUser();

    expect(await screen.findByText("Analyst")).toBeTruthy();
    expect(screen.getByText(copy["users.fields.role.help"])).toBeTruthy();
    expect(screen.queryByRole("button", { name: copy["users.role.save"] })).toBeNull();
  });
});
