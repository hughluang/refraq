/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, render, screen } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { BusinessEntity } from "@/features/entities/types";

const LABELS: Record<string, string> = {
  "entities.status.notServing": "Not in service",
  "entities.status.serving": "In service",
  "entities.status.unpublished": "Unpublished",
  "entities.status.publishing": "Publishing",
  "entities.status.published": "Published",
  "entities.status.deprecated": "Deprecated",
};

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) => LABELS[key] ?? key,
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

function entity(overrides: Record<string, unknown> = {}): BusinessEntity {
  return {
    id: "ent_1",
    table_name: "material",
    name: "Material",
    description: "x",
    deprecated_at: null,
    ever_published: false,
    current_version: {
      id: "encv_1",
      version: 1,
      superseded: false,
      publish_status: "unpublished",
      table_name: null,
      alignment: {
        table_present: false,
        definition_ahead: true,
        latest_job_id: null,
        latest_job_status: null,
      },
    },
    created_at: "2026-09-10T04:00:00Z",
    updated_at: "2026-09-10T04:00:00Z",
    ...overrides,
  } as BusinessEntity;
}

describe("PublishStatusBadge", () => {
  beforeEach(() => {
    stubDomApis();
  });

  afterEach(() => {
    cleanup();
  });

  it("renders unpublished", async () => {
    const { PublishStatusBadge } = await import(
      "@/features/entities/PublishStatusBadge"
    );
    render(
      createElement(
        MantineProvider,
        null,
        createElement(PublishStatusBadge, { publishStatus: "unpublished" }),
      ),
    );

    const badge = screen.getByText("Unpublished");
    expect(badge.textContent).toBe("Unpublished");
    expect(badge.closest(".mantine-Badge-root")).toHaveProperty(
      "style.textTransform",
      "none",
    );
  });

  it("keeps the version publish status when the entity is deprecated", async () => {
    const { PublishStatusBadge } = await import(
      "@/features/entities/PublishStatusBadge"
    );
    render(
      createElement(
        MantineProvider,
        null,
        createElement(PublishStatusBadge, { publishStatus: "published" }),
      ),
    );

    expect(screen.getByText("Published")).not.toBeNull();
    expect(screen.queryByText("Deprecated")).toBeNull();
  });
});

describe("EntityStatusBadge", () => {
  beforeEach(() => {
    stubDomApis();
  });

  afterEach(() => {
    cleanup();
  });

  it("stays in service when the current version is unpublished after a publish", async () => {
    const { EntityStatusBadge } = await import(
      "@/features/entities/EntityStatusBadge"
    );
    render(
      createElement(
        MantineProvider,
        null,
        createElement(EntityStatusBadge, {
          entity: entity({
            ever_published: true,
            current_version: {
              id: "encv_2",
              version: 2,
              superseded: false,
              publish_status: "unpublished",
              table_name: null,
              alignment: {
                table_present: false,
                definition_ahead: true,
                latest_job_id: null,
                latest_job_status: null,
              },
            },
          }),
        }),
      ),
    );

    expect(screen.getByText("In service")).not.toBeNull();
    expect(screen.queryByText("Unpublished")).toBeNull();
  });

  it("renders deprecated instead of service", async () => {
    const { EntityStatusBadge } = await import(
      "@/features/entities/EntityStatusBadge"
    );
    render(
      createElement(
        MantineProvider,
        null,
        createElement(EntityStatusBadge, {
          entity: entity({
            deprecated_at: "2026-09-10T04:00:00Z",
            ever_published: true,
          }),
        }),
      ),
    );

    expect(screen.getByText("Deprecated")).not.toBeNull();
    expect(screen.queryByText("In service")).toBeNull();
  });
});
