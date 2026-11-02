/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en-US/common.json";

const copy = en as Record<string, string>;
const listSources = vi.hoisted(() => vi.fn());
const push = vi.hoisted(() => vi.fn());

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
});
