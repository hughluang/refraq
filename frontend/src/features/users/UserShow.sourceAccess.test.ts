/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, render, screen } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en-US/common.json";

const copy = en as Record<string, string>;
const translate = (key: string) => copy[key] ?? key;
const USER_ID = "usr_ada";
const getUser = vi.hoisted(() => vi.fn());
const getUserGroups = vi.hoisted(() => vi.fn());
const getUserSubjectValues = vi.hoisted(() => vi.fn());
const listAllSubjectAttributes = vi.hoisted(() => vi.fn());
const getUserSourceAccess = vi.hoisted(() => vi.fn());

vi.mock("@refinedev/core", () => ({
  matchResourceFromRoute: () => ({ found: false }),
  useTranslate: () => translate,
  useNotification: () => ({ open: vi.fn() }),
  useCan: () => ({ data: { can: true } }),
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
  getUser: (...args: unknown[]) => getUser(...args),
  getUserGroups: (...args: unknown[]) => getUserGroups(...args),
  getUserSubjectValues: (...args: unknown[]) => getUserSubjectValues(...args),
  listAllSubjectAttributes: (...args: unknown[]) => listAllSubjectAttributes(...args),
  putUserGroups: vi.fn(),
  putUserSubjectValues: vi.fn(),
  getUserSourceAccess: (...args: unknown[]) => getUserSourceAccess(...args),
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

function shell(node: ReactNode) {
  return createElement(MantineProvider, { env: "test" }, node);
}

async function renderUser() {
  const { UserShow } = await import("@/features/users/UserShow");
  render(shell(createElement(UserShow, { userId: USER_ID })));
}

describe("User source access", () => {
  beforeEach(() => {
    stubDomApis();
    getUser.mockResolvedValue({
      user: {
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
      },
    });
    getUserGroups.mockResolvedValue({ groups: [] });
    getUserSubjectValues.mockResolvedValue({ values: {}, effective: {} });
    listAllSubjectAttributes.mockResolvedValue([]);
    getUserSourceAccess.mockResolvedValue({
      items: [
        {
          source_id: "src_ledger",
          key: "ledger",
          name: "Ledger",
          level: "maintainer",
          contributions: [
            { kind: "direct", subject_name: "Ada" },
            { kind: "group", subject_name: "East sales" },
            { kind: "identity", subject_name: "Super Admin" },
          ],
        },
      ],
    });
  });

  afterEach(() => {
    cleanup();
  });

  it("shows each reached Source, the effective level, and the path, and does not edit them", async () => {
    await renderUser();

    expect(await screen.findByRole("heading", { name: copy["sources.membership.userAccess"] })).toBeTruthy();
    expect(getUserSourceAccess).toHaveBeenCalledWith(USER_ID);
    const row = screen.getByText("Ledger").closest("tr");
    expect(row?.textContent).toContain("ledger");
    expect(row?.textContent).toContain(copy["sources.membership.level.maintainer"]);
    expect(row?.textContent).toContain(`${copy["sources.membership.path.direct"]} · Ada`);
    expect(row?.textContent).toContain(`${copy["sources.membership.path.group"]} · East sales`);
    expect(row?.textContent).toContain(copy["sources.membership.path.identity"]);
    expect(screen.queryByRole("button", { name: copy["sources.membership.change"] })).toBeNull();
    expect(screen.queryByRole("button", { name: copy["sources.membership.add"] })).toBeNull();
    expect(row?.querySelector("input, textarea, select")).toBeNull();
  });

  it("states when the user reaches no Sources", async () => {
    getUserSourceAccess.mockResolvedValue({ items: [] });
    await renderUser();

    expect(await screen.findByText(copy["sources.membership.userAccess.empty"])).toBeTruthy();
  });
});
