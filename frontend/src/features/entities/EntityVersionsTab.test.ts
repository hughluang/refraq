/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getVersion } from "@/features/entities/api";
import { EntityVersionsTab } from "@/features/entities/EntityVersionsTab";
import type { BusinessEntity, EntityVersion } from "@/features/entities/types";

const LABELS: Record<string, string> = {
  "entities.fields.version": "Version",
  "entities.fields.tableName": "Table name",
  "entities.fields.versionStatus": "Version status",
  "entities.fields.attributeCount": "Attribute count",
  "entities.fields.createdAt": "Created",
  "entities.fields.publishJob": "Publish job",
  "entities.fields.attributeName": "Attribute",
  "entities.fields.attributeType": "Attribute type",
  "entities.fields.attributeConfig": "Configuration",
  "entities.fields.required": "Required",
  "entities.fields.unique": "Unique",
  "entities.fields.indexed": "Indexed",
  "entities.fields.attributeDescription": "Attribute description",
  "entities.fields.maxLength": "Max length",
  "entities.status.published": "Published",
  "entities.status.unpublished": "Unpublished",
  "entities.attributeType.string": "Bounded text",
  "entities.attributes.config.maxLength": "Max length {{value}}",
  "entities.versions.view": "View",
  "entities.drop": "Drop table",
  "form.value.yes": "Yes",
  "form.value.no": "No",
  "common.empty": "No data",
};

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string, values?: Record<string, unknown>) => {
    const template = LABELS[key] ?? key;
    if (!values) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) =>
      String(values[name] ?? ""),
    );
  },
}));

vi.mock("@/features/entities/api", () => ({
  getVersion: vi.fn(),
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

function entity(): BusinessEntity {
  return {
    id: "ent_1",
    table_name: "attrtype_probe",
    name: "Probe",
    description: "x",
    deprecated_at: null,
    ever_published: true,
    current_version: {
      id: "encv_2",
      version: 2,
      publish_status: "unpublished",
      table_name: null,
      alignment: {
        table_present: false,
        latest_job_id: null,
        latest_job_status: null,
      },
    },
    created_at: "2026-09-10T04:00:00Z",
    updated_at: "2026-09-10T04:00:00Z",
  };
}

function version(overrides: Partial<EntityVersion> = {}): EntityVersion {
  return {
    id: "encv_1",
    entity_id: "ent_1",
    version: 1,
    publish_status: "published",
    attribute_count: 2,
    table_name: "attrtype_probe",
    alignment: {
      table_present: true,
      latest_job_id: "job_1",
      latest_job_status: "succeeded",
    },
    created_at: "2026-09-10T04:00:00Z",
    updated_at: "2026-09-10T05:00:00Z",
    ...overrides,
  };
}

function renderTab(
  versions: EntityVersion[],
  handlers?: {
    onOpenJob?: (jobId: string | null) => void;
    onViewError?: (err: unknown) => void;
    onDrop?: (version: EntityVersion) => void;
  },
) {
  return render(
    createElement(
      MantineProvider,
      { env: "test" },
      createElement(EntityVersionsTab, {
        entity: entity(),
        versions,
        canDropTable: false,
        busy: false,
        formatInstant: (value) => value ?? "—",
        onOpenJob: handlers?.onOpenJob ?? vi.fn(),
        onViewError: handlers?.onViewError ?? vi.fn(),
        onDrop: handlers?.onDrop ?? vi.fn(),
      }) as ReactNode,
    ),
  );
}

describe("EntityVersionsTab", () => {
  beforeEach(() => {
    stubDomApis();
    vi.mocked(getVersion).mockReset();
  });

  afterEach(() => {
    cleanup();
  });

  it("shows lifecycle columns and opens the saved attributes", async () => {
    vi.mocked(getVersion).mockResolvedValue({
      version: version({
        attributes: [
          {
            name: "sku",
            type: "string",
            required: true,
            unique: false,
            indexed: false,
            description: "SKU code",
            config: { max_length: 32 },
          },
        ],
      }),
    });
    const onOpenJob = vi.fn();
    renderTab(
      [
        version(),
        version({
          id: "encv_2",
          version: 2,
          publish_status: "unpublished",
          attribute_count: 3,
          table_name: null,
          alignment: {
            table_present: false,
            latest_job_id: null,
            latest_job_status: null,
          },
        }),
      ],
      { onOpenJob },
    );

    expect(screen.getByText("Attribute count")).toBeTruthy();
    expect(screen.getByText("Created")).toBeTruthy();
    expect(screen.getByText("2")).toBeTruthy();
    expect(screen.getByText("3")).toBeTruthy();
    expect(screen.getAllByText("2026-09-10T04:00:00Z")).toHaveLength(2);
    expect(screen.getAllByText("—").length).toBeGreaterThan(0);

    fireEvent.click(screen.getByRole("button", { name: "succeeded" }));
    expect(onOpenJob).toHaveBeenCalledWith("job_1");

    fireEvent.click(screen.getAllByRole("button", { name: "View" })[0]);
    expect(await screen.findByText("sku")).toBeTruthy();
    expect(screen.getByText("SKU code")).toBeTruthy();
    expect(screen.getByText("VARCHAR(32)")).toBeTruthy();
    expect(getVersion).toHaveBeenCalledWith("ent_1", "encv_1");
    expect(screen.getAllByText("sku")).toHaveLength(1);
  });

  it("does not open the drawer when the version read fails", async () => {
    vi.mocked(getVersion).mockRejectedValue(new Error("offline"));
    const onViewError = vi.fn();
    renderTab([version({ attributes: undefined })], { onViewError });

    fireEvent.click(screen.getByRole("button", { name: "View" }));
    await waitFor(() => {
      expect(onViewError).toHaveBeenCalledTimes(1);
    });
    expect(screen.queryByText("sku")).toBeNull();
    expect(screen.queryByRole("dialog")).toBeNull();
  });
});
