/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en-US/common.json";
import type {
  CatalogIndexState,
  EmbedSchedule,
  EntityIndexState,
  ModelService,
  PurposeState,
} from "@/features/model-services/types";

const getEmbeddingPurpose = vi.hoisted(() => vi.fn());
const getModelService = vi.hoisted(() => vi.fn());
const listModelServices = vi.hoisted(() => vi.fn());
const forceEmbeddingGeneration = vi.hoisted(() => vi.fn());
const cleanupEmbeddingPurpose = vi.hoisted(() => vi.fn());
const runSchedule = vi.hoisted(() => vi.fn());
const access = vi.hoisted(() => ({
  write: true,
  remove: true,
  schedules: true,
}));

vi.mock("@refinedev/core", () => ({
  matchResourceFromRoute: () => ({ found: false }),
  useTranslate: () => (key: string, options?: Record<string, unknown>) => {
    const template = (en as Record<string, string>)[key] ?? key;
    if (!options) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) =>
      String(options[name] ?? ""),
    );
  },
  useCan: ({ resource, action }: { resource: string; action: string }) => {
    if (resource === "schedules") return { data: { can: access.schedules } };
    if (action === "delete") return { data: { can: access.remove } };
    if (action === "edit" || action === "create") {
      return { data: { can: access.write } };
    }
    return { data: { can: true } };
  },
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

vi.mock("@/features/schedules/api", () => ({
  runSchedule,
}));

vi.mock("@/features/model-services/api", () => ({
  getEmbeddingPurpose,
  getModelService,
  listModelServices,
  activateModelService: vi.fn(),
  cleanupEmbeddingPurpose,
  closeEmbeddingPurpose: vi.fn(),
  createModelService: vi.fn(),
  deleteModelService: vi.fn(),
  openEmbeddingPurpose: vi.fn(),
  forceEmbeddingGeneration,
  patchModelService: vi.fn(),
  testModelService: vi.fn(),
}));

const copy = en as Record<string, string>;

function schedule(id: string, cron: string): EmbedSchedule {
  return {
    id,
    enabled: true,
    cron,
    interval_seconds: null,
    next_run_at: "2026-11-11T03:00:00Z",
  };
}

function entityIndex(patch: Partial<EntityIndexState> = {}): EntityIndexState {
  return {
    ready: false,
    generation: null,
    index_status: "none",
    coverage: { written: 0, failed: 0, attempted: 0 },
    progress: null,
    failure_summary: null,
    schedule: null,
    rebuild_owed: false,
    ...patch,
  };
}

function purposeState(
  closed: boolean,
  patch: {
    catalog_index?: Partial<CatalogIndexState>;
    entity_index?: Partial<EntityIndexState>;
    embed_schedule?: EmbedSchedule | null;
  } = {},
): PurposeState {
  const catalog: CatalogIndexState = {
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
    ...patch.catalog_index,
  };
  return {
    purpose: "embedding",
    closed,
    ready: !closed,
    in_use_id: "svc_1",
    generation: 2,
    index_status: "failed",
    catalog_index: catalog,
    entity_index: entityIndex(patch.entity_index),
    embed_schedule:
      patch.embed_schedule === undefined ? null : patch.embed_schedule,
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

function listedService(
  patch: Partial<ModelService> & Pick<ModelService, "id" | "display_name" | "in_use">,
): ModelService {
  return {
    purpose: "embedding",
    protocol: "openai_compat",
    url: "https://embed.example/v1/embeddings",
    model: "text-embedding",
    timeout_sec: 30,
    batch_limit: 32,
    has_secret: true,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...patch,
  };
}

async function openStatusTab(
  closed: boolean,
  patch?: Parameters<typeof purposeState>[1],
) {
  getEmbeddingPurpose.mockResolvedValue(purposeState(closed, patch));
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
    getModelService.mockResolvedValue(null);
  });

  afterEach(() => {
    cleanup();
    getEmbeddingPurpose.mockReset();
    getModelService.mockReset();
    listModelServices.mockReset();
    forceEmbeddingGeneration.mockReset();
    cleanupEmbeddingPurpose.mockReset();
    runSchedule.mockReset();
    access.write = true;
    access.remove = true;
    access.schedules = true;
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
    expect(copy["modelServices.close.confirmBody"]).toMatch(/shared model/);
    expect(copy["modelServices.close.confirmBody"]).toMatch(/Generation does not change/);
    expect(copy["modelServices.close.confirmBody"]).toMatch(/Catalog index/);
    expect(copy["modelServices.close.confirmBody"]).toMatch(/Entity index/);
    expect(copy["modelServices.forceGeneration.confirmBody"]).toMatch(/shared generation/);
    expect(copy["modelServices.forceGeneration.confirmBody"]).toMatch(/Catalog/);
    expect(copy["modelServices.forceGeneration.confirmBody"]).toMatch(/Entity/);

    cleanup();
    await openStatusTab(true);
    fireEvent.click(screen.getByRole("button", { name: copy["modelServices.open"] }));
    expect(screen.getByText(copy["modelServices.open.confirmBody"])).toBeTruthy();
    expect(copy["modelServices.open.confirmBody"]).toMatch(/shared model/);
    expect(copy["modelServices.open.confirmBody"]).toMatch(/Generation does not change/);
    expect(copy["modelServices.open.confirmBody"]).toMatch(/Catalog/);
    expect(copy["modelServices.open.confirmBody"]).toMatch(/Entity/);
  });

  it("shows each index from the purpose read model", async () => {
    expect(copy["modelServices.entity.index.ready"]).toBe("Entity ready");
    expect(copy["modelServices.entity.index.ready"]).not.toMatch(
      /complete|coverage|every incremental/i,
    );

    await openStatusTab(false, {
      embed_schedule: schedule("sch_catalog", "0 4 * * *"),
      catalog_index: {
        generation_last_swept: 41,
        progress: "catalog sweep moving",
        coverage: {
          objects_written: 4,
          columns_written: 8,
          objects_failed: 1,
          columns_failed: 0,
          objects_attempted: 9,
          columns_attempted: 12,
        },
      },
      entity_index: {
        ready: false,
        generation: null,
        index_status: "failed",
        coverage: { written: 1, failed: 2, attempted: 3 },
        progress: "initial sweep stopped",
        failure_summary: "initial sweep left two targets",
        schedule: schedule("sch_entity", "0 3 * * *"),
        rebuild_owed: true,
      },
    });

    const shared = await screen.findByRole("region", {
      name: copy["modelServices.shared.title"],
    });
    const catalog = screen.getByRole("region", {
      name: copy["modelServices.catalog.title"],
    });
    const entity = screen.getByRole("region", {
      name: copy["modelServices.entity.title"],
    });
    expect(
      shared.contains(
        screen.getByRole("button", { name: copy["modelServices.close"] }),
      ),
    ).toBe(true);
    expect(
      catalog.contains(
        screen.getByRole("button", { name: copy["modelServices.close"] }),
      ),
    ).toBe(false);
    const catalogText = catalog.textContent ?? "";
    const entityText = entity.textContent ?? "";
    expect(catalogText).not.toContain(copy["modelServices.entity.title"]);
    expect(catalogText).toContain(copy["modelServices.index.ready"]);
    expect(catalogText).toContain("41");
    expect(catalogText).toContain("Objects written 4, failed 1, attempted 9");
    expect(catalogText).toContain("Columns written 8, failed 0, attempted 12");
    expect(catalogText).toContain("catalog sweep moving");
    expect(catalogText).toContain("0 4 * * *");
    expect(catalogText).toContain(copy["modelServices.index.scheduleEnabled"]);
    expect(catalogText).not.toContain(copy["modelServices.index.rebuildOwed"]);
    expect(entityText).toContain(copy["modelServices.entity.index.failed"]);
    expect(entityText).toContain(copy["modelServices.index.generationNone"]);
    expect(entityText).toContain("Written 1, failed 2, attempted 3");
    expect(entityText).toContain("initial sweep stopped");
    expect(entityText).toContain("initial sweep left two targets");
    expect(entityText).toContain(copy["modelServices.index.rebuildOwed"]);
    expect(entityText).toContain("0 3 * * *");
    expect(entityText).not.toContain(copy["modelServices.entity.readyNote"]);
    expect(entityText).not.toContain(copy["modelServices.entity.index.ready"]);

    cleanup();
    await openStatusTab(false, {
      entity_index: {
        ready: true,
        generation: 5,
        index_status: "ready",
        coverage: { written: 10, failed: 1, attempted: 11 },
        failure_summary: "one incremental target is missing",
        rebuild_owed: false,
      },
    });
    const readyEntity = await screen.findByRole("region", {
      name: copy["modelServices.entity.title"],
    });
    const readyText = readyEntity.textContent ?? "";
    expect(readyText).toContain(copy["modelServices.entity.index.ready"]);
    expect(readyText).toContain(copy["modelServices.entity.readyNote"]);
    expect(readyText).toContain("one incremental target is missing");
    expect(readyText).toContain("Written 10, failed 1, attempted 11");
    expect(readyText).toContain("5");
    expect(readyText).not.toContain(copy["modelServices.index.rebuildOwed"]);
  });

  it("shows the in-use model apart from either index", async () => {
    getModelService.mockResolvedValue({
      id: "svc_1",
      purpose: "embedding",
      protocol: "openai_compat",
      display_name: "Embed",
      url: "https://embed.example/v1/embeddings",
      model: "text-embedding-shared",
      timeout_sec: 45,
      batch_limit: 7,
      has_secret: true,
      in_use: true,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
      api_key: "sent-secret-value",
    });
    await openStatusTab(false);
    const shared = await screen.findByRole("region", {
      name: copy["modelServices.shared.title"],
    });
    await waitFor(() => {
      expect(shared.textContent ?? "").toContain(
        "https://embed.example/v1/embeddings",
      );
    });
    expect(getModelService).toHaveBeenCalledWith("svc_1");
    const sharedText = shared.textContent ?? "";
    expect(sharedText).toContain("text-embedding-shared");
    expect(sharedText).toContain("45");
    expect(sharedText).toContain("7");
    expect(sharedText).toContain(copy["modelServices.fields.url"]);
    expect(sharedText).toContain(copy["modelServices.fields.model"]);
    expect(sharedText).toContain(copy["modelServices.fields.timeout_sec"]);
    expect(sharedText).toContain(copy["modelServices.fields.batch_limit"]);
    expect(sharedText).toContain(copy["modelServices.status.secretSet"]);
    expect(sharedText).not.toContain("sent-secret-value");
    const catalog = screen.getByRole("region", {
      name: copy["modelServices.catalog.title"],
    });
    expect(catalog.textContent ?? "").not.toContain(
      "https://embed.example/v1/embeddings",
    );
  });

  it("shows status to readers and keeps schedule links behind their permission", async () => {
    access.write = false;
    access.remove = false;
    access.schedules = true;
    await openStatusTab(false, {
      embed_schedule: schedule("sch_catalog", "0 4 * * *"),
      entity_index: {
        ready: true,
        index_status: "ready",
        schedule: schedule("sch_entity", "0 3 * * *"),
      },
    });
    expect(
      await screen.findByText(copy["modelServices.entity.index.ready"]),
    ).toBeTruthy();
    expect(screen.getByText(copy["modelServices.index.ready"])).toBeTruthy();
    expect(screen.getByText(copy["modelServices.entity.readyNote"])).toBeTruthy();
    expect(screen.getByText(copy["schedules.title"])).toBeTruthy();
    expect(screen.queryByRole("button", { name: copy["modelServices.close"] })).toBeNull();
    expect(
      screen.queryByRole("button", { name: copy["modelServices.forceGeneration"] }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: copy["modelServices.cleanup"] }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: copy["modelServices.rebuild.catalog"] }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: copy["modelServices.rebuild.entity"] }),
    ).toBeNull();

    cleanup();
    access.write = true;
    access.remove = true;
    access.schedules = false;
    await openStatusTab(false, {
      embed_schedule: schedule("sch_catalog", "0 4 * * *"),
      entity_index: {
        schedule: schedule("sch_entity", "0 3 * * *"),
      },
    });
    expect(
      await screen.findByRole("button", { name: copy["modelServices.close"] }),
    ).toBeTruthy();
    expect(screen.queryByText(copy["schedules.title"])).toBeNull();
    expect(
      screen.queryByRole("button", { name: copy["modelServices.rebuild.catalog"] }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: copy["modelServices.rebuild.entity"] }),
    ).toBeNull();
  });

  it("rebuilds one index from its own schedule", async () => {
    runSchedule.mockResolvedValue({});
    await openStatusTab(false, {
      embed_schedule: schedule("sch_catalog", "0 4 * * *"),
      entity_index: {
        schedule: schedule("sch_entity", "0 3 * * *"),
      },
    });
    const catalog = await screen.findByRole("region", {
      name: copy["modelServices.catalog.title"],
    });
    const entity = screen.getByRole("region", {
      name: copy["modelServices.entity.title"],
    });
    const catalogRebuild = screen.getByRole("button", {
      name: copy["modelServices.rebuild.catalog"],
    });
    const entityRebuild = screen.getByRole("button", {
      name: copy["modelServices.rebuild.entity"],
    });
    expect(catalog.contains(catalogRebuild)).toBe(true);
    expect(entity.contains(entityRebuild)).toBe(true);
    expect(catalog.contains(entityRebuild)).toBe(false);

    fireEvent.click(catalogRebuild);
    expect(screen.getByText(copy["modelServices.rebuild.catalogBody"])).toBeTruthy();
    expect(copy["modelServices.rebuild.catalogBody"]).toMatch(/Entity index is not rebuilt/);
    fireEvent.click(screen.getByRole("button", { name: copy["common.cancel"] }));
    expect(runSchedule).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: copy["modelServices.rebuild.catalog"] }));
    fireEvent.click(screen.getByRole("button", { name: copy["common.confirm"] }));
    await waitFor(() => expect(runSchedule).toHaveBeenCalledTimes(1));
    expect(runSchedule).toHaveBeenCalledWith("sch_catalog");
    expect(cleanupEmbeddingPurpose).not.toHaveBeenCalled();
    expect(forceEmbeddingGeneration).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: copy["modelServices.rebuild.entity"] }));
    expect(screen.getByText(copy["modelServices.rebuild.entityBody"])).toBeTruthy();
    expect(copy["modelServices.rebuild.entityBody"]).toMatch(/Catalog index is not rebuilt/);
    fireEvent.click(screen.getByRole("button", { name: copy["common.confirm"] }));
    expect(runSchedule).toHaveBeenCalledTimes(2);
    expect(runSchedule).toHaveBeenLastCalledWith("sch_entity");
  });

  it("names both indexes before cleanup and does not refill them", async () => {
    await openStatusTab(true);
    fireEvent.click(
      await screen.findByRole("button", { name: copy["modelServices.cleanup"] }),
    );
    const body = copy["modelServices.cleanup.confirmBody"];
    expect(await screen.findByText(body)).toBeTruthy();
    expect(body).toMatch(/Catalog index/);
    expect(body).toMatch(/Entity index/);
    expect(body).toMatch(/does not start a refill/i);
    expect(cleanupEmbeddingPurpose).not.toHaveBeenCalled();
    expect(runSchedule).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: copy["common.cancel"] }));
    expect(cleanupEmbeddingPurpose).not.toHaveBeenCalled();
    expect(runSchedule).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: copy["modelServices.cleanup"] }));
    fireEvent.click(screen.getByRole("button", { name: copy["common.confirm"] }));
    expect(cleanupEmbeddingPurpose).toHaveBeenCalledTimes(1);
    expect(forceEmbeddingGeneration).not.toHaveBeenCalled();
    expect(runSchedule).not.toHaveBeenCalled();
  });

  it("explains enable and in-use delete for both searches", async () => {
    const enableBody = copy["modelServices.activate.confirmBody"];
    expect(enableBody).toMatch(/Catalog/);
    expect(enableBody).toMatch(/Entity/);
    expect(enableBody).toMatch(/both ready marks/);
    expect(enableBody).toMatch(/both site embed schedules/);
    expect(enableBody).toMatch(/Catalog Search stays lexical/);
    expect(enableBody).toMatch(/Entity semantic search is refused/);
    expect(enableBody).toMatch(/does not fall back to a lexical rank/);
    expect(enableBody).not.toMatch(/Search stays lexical until that Job/);
    expect(enableBody).not.toMatch(/Entity semantic search stays lexical/);
    expect(enableBody).not.toMatch(/the ready mark/);
    expect(enableBody).not.toMatch(/the site embed schedule/);

    const success = copy["modelServices.activate.success"];
    expect(success).toMatch(/both ready marks/i);
    expect(success).toMatch(/both site embed schedules/i);
    expect(success).toMatch(/Catalog Search stays lexical/);
    expect(success).toMatch(/Entity semantic search is refused/);
    expect(success).not.toMatch(/Search stays lexical until the embed Job/);
    expect(success).not.toMatch(/Entity semantic search stays lexical/);

    const deleteBody = copy["modelServices.delete.confirmInUse"];
    expect(deleteBody).toMatch(/Catalog Search becomes lexical/);
    expect(deleteBody).toMatch(/Entity semantic search stops/);
    expect(deleteBody).toMatch(/Neither index is cleaned/);
    expect(deleteBody).toMatch(/in-flight embed Job keeps running/);
    expect(deleteBody).not.toMatch(/ready/i);
    expect(deleteBody).not.toMatch(/schedule/i);

    getEmbeddingPurpose.mockResolvedValue(purposeState(false));
    listModelServices.mockResolvedValue({
      items: [
        listedService({
          id: "svc_draft",
          display_name: "Draft embed",
          in_use: false,
        }),
        listedService({
          id: "svc_1",
          display_name: "Live embed",
          in_use: true,
        }),
      ],
      total: 2,
      limit: 50,
      offset: 0,
    });
    const { ModelServiceList } = await import(
      "@/features/model-services/ModelServiceList"
    );
    render(
      createElement(
        MantineProvider,
        { env: "test" },
        createElement(ModelServiceList),
      ),
    );

    fireEvent.click(
      await screen.findByRole("button", {
        name: "More actions for Draft embed",
      }),
    );
    fireEvent.click(
      screen.getByRole("menuitem", { name: copy["modelServices.activate"] }),
    );
    expect(await screen.findByText(enableBody)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: copy["common.cancel"] }));

    fireEvent.click(
      screen.getByRole("button", { name: "More actions for Live embed" }),
    );
    fireEvent.click(
      screen.getByRole("menuitem", { name: copy["actions.delete"] }),
    );
    expect(screen.getByText(deleteBody)).toBeTruthy();
  });
});
