/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en-US/common.json";
import type { PurposeState } from "@/features/model-services/types";

const getEmbeddingPurpose = vi.hoisted(() => vi.fn());
const listModelServices = vi.hoisted(() => vi.fn());
const forceEmbeddingGeneration = vi.hoisted(() => vi.fn());

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
  forceEmbeddingGeneration,
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
    index_status: "failed",
    catalog_index: {
      ready: !closed,
      generation_last_swept: 2,
      index_status: "ready",
      coverage: {
        objects_written: 0,
        columns_written: 0,
        objects_failed: 0,
        columns_failed: 0,
        objects_attempted: 0,
        columns_attempted: 0,
      },
      progress: null,
      failure_summary: null,
      rebuild_owed: false,
    },
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

    expect(copy["modelServices.index.ready"]).toMatch(/^Catalog /);
    expect(await screen.findByText(copy["modelServices.index.ready"])).toBeTruthy();
    expect(screen.queryByText(copy["modelServices.index.failed"])).toBeNull();
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

  it("explains close, reopen, and force-generation", async () => {
    await openStatusTab(false);
    fireEvent.click(
      await screen.findByRole("button", { name: copy["modelServices.forceGeneration"] }),
    );
    expect(
      await screen.findByText(copy["modelServices.forceGeneration.confirmBody"]),
    ).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: copy["common.confirm"] }));
    expect(forceEmbeddingGeneration).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("button", { name: copy["modelServices.close"] }));
    expect(screen.getByText(copy["modelServices.close.confirmBody"])).toBeTruthy();
    expect(copy["modelServices.close.confirmBody"]).toMatch(/Generation does not change/);

    cleanup();
    await openStatusTab(true);
    fireEvent.click(screen.getByRole("button", { name: copy["modelServices.open"] }));
    expect(screen.getByText(copy["modelServices.open.confirmBody"])).toBeTruthy();
    expect(copy["modelServices.open.confirmBody"]).toMatch(/Generation does not change/);
  });

  it("keeps cleanup confirmation on the Catalog index", async () => {
    await openStatusTab(true);
    fireEvent.click(
      await screen.findByRole("button", { name: copy["modelServices.cleanup"] }),
    );
    const body = copy["modelServices.cleanup.confirmBody"];
    expect(await screen.findByText(body)).toBeTruthy();
    expect(body).toMatch(/Catalog/);
    expect(body).not.toMatch(/entity/i);
  });
});
