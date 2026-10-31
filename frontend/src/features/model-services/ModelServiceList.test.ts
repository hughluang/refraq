/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en-US/common.json";
import type { PurposeState } from "@/features/model-services/types";

const getEmbeddingPurpose = vi.hoisted(() => vi.fn());
const listModelServices = vi.hoisted(() => vi.fn());

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) => (en as Record<string, string>)[key] ?? key,
  useCan: () => ({ data: { can: true } }),
  useNotification: () => ({ open: vi.fn() }),
  useBreadcrumb: () => ({ breadcrumbs: [] }),
  CanAccess: ({ children }: { children?: ReactNode }) => children,
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/console/model-services",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) =>
    createElement("a", { href }, children),
  useLinkStatus: () => ({ pending: false }),
}));

vi.mock("@/components/layout/PageChrome", () => ({
  PageChrome: ({
    tabs,
    children,
  }: {
    tabs?: ReactNode;
    children?: ReactNode;
  }) => createElement("div", null, tabs, children),
}));

vi.mock("@/components/navigation/ConsoleLink", () => ({
  ConsoleLink: ({ children }: { children?: ReactNode }) => children,
}));

vi.mock("@/features/model-services/api", () => ({
  getEmbeddingPurpose,
  listModelServices,
  activateModelService: vi.fn(),
  cleanupEmbeddingPurpose: vi.fn(),
  closeEmbeddingPurpose: vi.fn(),
  createModelService: vi.fn(),
  deleteModelService: vi.fn(),
  openEmbeddingPurpose: vi.fn(),
  patchModelService: vi.fn(),
  testModelService: vi.fn(),
}));

const copy = en as Record<string, string>;

function purposeState(closed: boolean): PurposeState {
  return {
    purpose: "embedding",
    closed,
    ready: !closed,
    in_use_id: "svc_1",
    generation: 2,
    index_status: "ready",
    embed_schedule: null,
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
}

async function openStatusTab(closed: boolean) {
  getEmbeddingPurpose.mockResolvedValue(purposeState(closed));
  listModelServices.mockResolvedValue({ items: [], total: 0, limit: 50, offset: 0 });
  const { ModelServiceList } = await import("@/features/model-services/ModelServiceList");
  render(
    createElement(
      MantineProvider,
      { env: "test" },
      createElement(ModelServiceList),
    ),
  );
  fireEvent.click(await screen.findByRole("tab", { name: copy["modelServices.tabs.status"] }));
}

describe("ModelServiceList status", () => {
  beforeEach(() => {
    stubDomApis();
  });

  afterEach(() => {
    cleanup();
    getEmbeddingPurpose.mockReset();
    listModelServices.mockReset();
  });

  it("explains a closed purpose without announcing an alert", async () => {
    await openStatusTab(true);

    const title = await screen.findByText(copy["modelServices.closed.noteTitle"]);
    const note = screen.getByText(copy["modelServices.closed.note"]);
    expect(title.closest("[role='alert']")).toBeNull();
    expect(note.closest("[role='alert']")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("leaves the explanation off while the purpose is open", async () => {
    await openStatusTab(false);

    expect(await screen.findByText(copy["modelServices.index.ready"])).toBeTruthy();
    expect(screen.getByText(copy["modelServices.status.open"])).toBeTruthy();
    expect(screen.queryByText(copy["modelServices.closed.noteTitle"])).toBeNull();
    expect(screen.queryByText(copy["modelServices.closed.note"])).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("keeps the closed badge and the open and cleanup actions", async () => {
    await openStatusTab(true);

    expect(await screen.findByText(copy["modelServices.status.closed"])).toBeTruthy();
    expect(screen.getByRole("button", { name: copy["modelServices.open"] })).toBeTruthy();
    expect(screen.getByRole("button", { name: copy["modelServices.cleanup"] })).toBeTruthy();
  });
});
