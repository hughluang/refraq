/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import en from "@/locales/en-US/common.json";

const copy = en as Record<string, string>;
const listSources = vi.hoisted(() => vi.fn());
const push = vi.hoisted(() => vi.fn());
const permissions = vi.hoisted(() => ({ data: ["sources:read"] as string[] }));
const listEverySourceMemberships = vi.hoisted(() => vi.fn());
const createEverySourceMembership = vi.hoisted(() => vi.fn());
const changeEverySourceMembership = vi.hoisted(() => vi.fn());
const deleteEverySourceMembership = vi.hoisted(() => vi.fn());

vi.mock("@/features/sources/api/sources", () => ({
  listSources: (...args: unknown[]) => listSources(...args),
  getAccessSchema: vi.fn(),
  createSource: vi.fn(),
  deleteSource: vi.fn(),
  getSourceAccess: vi.fn(),
  patchSource: vi.fn(),
  testSource: vi.fn(),
  testSourceDraft: vi.fn(),
  getSource: vi.fn(),
}));

vi.mock("@/features/sources/api/memberships", () => ({
  listEverySourceMemberships: (...args: unknown[]) => listEverySourceMemberships(...args),
  createEverySourceMembership: (...args: unknown[]) => createEverySourceMembership(...args),
  changeEverySourceMembership: (...args: unknown[]) => changeEverySourceMembership(...args),
  deleteEverySourceMembership: (...args: unknown[]) => deleteEverySourceMembership(...args),
}));

vi.mock("@/features/branding/BrandingProvider", () => ({
  useBranding: () => ({ brandName: "Refraq" }),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/console/sources",
  useRouter: () => ({ push, replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) =>
    createElement("a", { href }, children),
  useLinkStatus: () => ({ pending: false }),
}));

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string, options?: Record<string, unknown>) => {
    const template = copy[key] ?? key;
    if (!options) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) =>
      String(options[name] ?? ""),
    );
  },
  useNotification: () => ({ open: vi.fn() }),
  useCan: () => ({ data: { can: true } }),
  usePermissions: () => ({ data: permissions.data, isLoading: false }),
  useBreadcrumb: () => ({ breadcrumbs: [] }),
  CanAccess: ({ children }: { children?: ReactNode }) => children,
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
  if (document.fonts == null) {
    Object.defineProperty(document, "fonts", {
      configurable: true,
      value: { addEventListener() {}, removeEventListener() {} },
    });
  }
}

function shell(node: ReactNode) {
  return createElement(MantineProvider, { env: "test" }, node);
}

function page(items: unknown[]) {
  return { items, total: items.length, limit: 100, offset: 0 };
}

const LEDGER = {
  id: "src_1",
  key: "ledger",
  locator_key: "ledger",
  name: "Ledger",
  kind: "database",
  status: "active",
  description: null,
  engine: "postgresql",
  access: { host: "db.internal", database: "ledger" },
  has_access: true,
  access_updated_at: null,
};

async function renderList() {
  const { SourceList } = await import("@/features/sources/SourceList");
  render(shell(createElement(SourceList)));
}

describe("SourceList", () => {
  beforeEach(() => {
    stubDomApis();
    listSources.mockReset();
    push.mockReset();
    permissions.data = ["sources:read"];
    listEverySourceMemberships.mockReset();
    createEverySourceMembership.mockReset();
    changeEverySourceMembership.mockReset();
    deleteEverySourceMembership.mockReset();
    listEverySourceMemberships.mockResolvedValue({ items: [] });
  });

  afterEach(() => {
    cleanup();
  });

  it("opens create on the record route and does not author in a dialog", async () => {
    listSources.mockResolvedValue(page([]));
    await renderList();

    const create = await screen.findAllByRole("link", { name: copy["sources.create"] });
    expect(create.length).toBeGreaterThan(0);
    for (const link of create) {
      expect(link.getAttribute("href")).toBe("/console/sources/new");
    }
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("opens a row on the record and sends diffs to that record's tab", async () => {
    listSources.mockResolvedValue(page([LEDGER]));
    await renderList();

    const name = await screen.findByRole("link", { name: "Ledger" });
    expect(name.getAttribute("href")).toBe("/console/sources/src_1");
    expect(name.getAttribute("href")).not.toContain("structure-diffs");

    fireEvent.click(screen.getByRole("button", { name: copy["structureDiffs.open"] }));
    expect(push).toHaveBeenCalledWith("/console/sources/src_1?tab=diffs");

    fireEvent.click(screen.getByRole("button", { name: copy["schedules.related.open"] }));
    expect(push).toHaveBeenCalledWith("/console/sources/src_1/schedules");
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("states the fresh-site rule when a reader has no Sources, and keeps no-match separate", async () => {
    listSources.mockResolvedValue(page([]));
    await renderList();

    expect(await screen.findByText(copy["sources.empty.fresh"])).toBeTruthy();
    expect(screen.queryByText(copy["sources.list.noMatch"])).toBeNull();

    fireEvent.change(screen.getByRole("textbox", { name: copy["common.list.search"] }), {
      target: { value: "missing" },
    });
    fireEvent.keyDown(screen.getByRole("textbox", { name: copy["common.list.search"] }), {
      key: "Enter",
    });

    expect(await screen.findByText(copy["sources.list.noMatch"])).toBeTruthy();
    expect(screen.queryByText(copy["sources.empty.fresh"])).toBeNull();
  });

  it("links an identity row by id and does not invent access, host, or catalog actions", async () => {
    permissions.data = ["sources:access_manage"];
    listSources.mockResolvedValue(
      page([
        {
          id: "src_beta",
          key: "beta",
          name: "Beta",
          kind: "database",
          engine: "postgresql",
          status: "active",
        },
      ]),
    );
    await renderList();

    const name = await screen.findByRole("link", { name: "Beta" });
    expect(name.getAttribute("href")).toBe("/console/sources/src_beta");
    const row = name.closest("tr");
    expect(row?.textContent).toContain("beta");
    expect(row?.textContent).toContain(copy["sources.engines.postgresql"]);
    expect(row?.textContent).toContain(copy["sources.status.active"]);
    expect(row?.textContent).not.toContain("db.internal");
    expect(row?.textContent).not.toContain(copy["sources.fields.hasAccessNo"]);
    expect(row?.textContent).not.toContain(copy["sources.fields.hasAccessYes"]);
    expect(screen.queryByRole("button", { name: copy["structureDiffs.open"] })).toBeNull();
  });

  it("puts every-Source access in the page header only for sources:access_manage", async () => {
    listSources.mockResolvedValue(page([]));
    await renderList();
    expect(screen.queryByRole("button", { name: copy["sources.membership.every"] })).toBeNull();
    cleanup();

    permissions.data = ["sources:access_manage"];
    listEverySourceMemberships.mockResolvedValue({
      items: [
        {
          id: "mem_1",
          subject: { type: "role", id: "role_1", display_name: "Analyst", missing: false },
          target: "*",
          level: "viewer",
          created_at: "2026-09-10T04:00:00Z",
          updated_at: "2026-09-10T04:00:00Z",
        },
      ],
    });
    await renderList();

    const action = await screen.findByRole("button", { name: copy["sources.membership.every"] });
    const search = screen.getByRole("textbox", { name: copy["common.list.search"] });
    let node: HTMLElement | null = search;
    let toolbar: HTMLElement | null = null;
    while (node) {
      if (node.getAttribute("data-page-header") != null) break;
      toolbar = node;
      node = node.parentElement;
    }
    expect(toolbar?.contains(action)).toBe(false);
    expect(document.querySelector("[data-page-header]")?.contains(action)).toBe(true);

    changeEverySourceMembership.mockResolvedValue({ membership: { id: "mem_1" } });
    deleteEverySourceMembership.mockResolvedValue(undefined);
    fireEvent.click(action);
    const dialog = await screen.findByRole("dialog", { name: copy["sources.membership.every"] });
    expect(within(dialog).getByText("Analyst")).toBeTruthy();
    expect(within(dialog).getByText(copy["sources.membership.level.viewer"])).toBeTruthy();

    fireEvent.click(within(dialog).getByRole("button", { name: copy["sources.membership.change"] }));
    const form = await screen.findByRole("dialog", { name: copy["sources.membership.change"] });
    fireEvent.mouseDown(within(form).getByRole("combobox", { name: copy["sources.membership.level"] }));
    fireEvent.click(
      screen.getByRole("option", {
        name: copy["sources.membership.level.maintainer"],
        hidden: true,
      }),
    );
    fireEvent.click(within(form).getByRole("button", { name: copy["sources.membership.change"] }));
    await waitFor(() =>
      expect(changeEverySourceMembership).toHaveBeenCalledWith("mem_1", "maintainer"),
    );

    fireEvent.click(screen.getByRole("button", { name: copy["sources.membership.remove"] }));
    const confirm = await screen.findByRole("dialog", {
      name: copy["sources.membership.removeTitle"],
    });
    fireEvent.click(within(confirm).getByRole("button", { name: copy["sources.membership.remove"] }));
    await waitFor(() => expect(deleteEverySourceMembership).toHaveBeenCalledWith("mem_1"));
  });

  it("shows the empty sentence when every-Source access has no rows", async () => {
    permissions.data = ["sources:access_manage"];
    listSources.mockResolvedValue(page([]));
    await renderList();

    fireEvent.click(
      await screen.findByRole("button", { name: copy["sources.membership.every"] }),
    );
    const dialog = await screen.findByRole("dialog", { name: copy["sources.membership.every"] });
    expect(await within(dialog).findByText(copy["sources.membership.empty"])).toBeTruthy();
  });

  it("does not describe a failed membership load as an empty list", async () => {
    permissions.data = ["sources:access_manage"];
    listSources.mockResolvedValue(page([]));
    listEverySourceMemberships.mockRejectedValue(
      new ApiError(404, "HTTP_NOT_FOUND", "Not Found", "req-missing-route"),
    );
    await renderList();

    fireEvent.click(
      await screen.findByRole("button", { name: copy["sources.membership.every"] }),
    );
    const dialog = await screen.findByRole("dialog", { name: copy["sources.membership.every"] });
    await waitFor(() => expect(listEverySourceMemberships).toHaveBeenCalled());
    expect(within(dialog).queryByText(copy["sources.membership.empty"])).toBeNull();
  });
});
