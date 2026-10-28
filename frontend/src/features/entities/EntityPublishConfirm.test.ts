/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { previewEntityPublish } from "@/features/entities/api";
import { EntityPublishConfirm } from "@/features/entities/EntityPublishConfirm";

const LABELS: Record<string, string> = {
  "entities.publish.confirmTitle": "Publish this Business Entity?",
  "entities.publish.confirmBody": "Publish “{{name}}”. Creates the table.",
  "entities.publish.confirmBodySuccessor":
    "Publish “{{name}}”. Creates an empty table. Rows stay on the previous table.",
  "entities.publish.confirmDeleteAll":
    "This publish will delete every change entry.",
  "entities.publish.confirmDeleteExpired":
    "This publish will delete change entries already past the new retention.",
  "entities.publish": "Publish",
  "entities.publish.noIncompatible": "No incompatible write nodes",
  "common.cancel": "Cancel",
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
  previewEntityPublish: vi.fn(),
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

function renderConfirm() {
  render(
    createElement(
      MantineProvider,
      null,
      createElement(EntityPublishConfirm, {
        opened: true,
        onClose: () => undefined,
        entityId: "ent_1",
        versionId: "ver_1",
        name: "Material",
        everPublished: true,
        loading: false,
        onConfirm: () => undefined,
      }),
    ),
  );
}

describe("publish confirmation change-log sentence", () => {
  beforeEach(() => {
    stubDomApis();
    vi.clearAllMocks();
  });

  afterEach(() => {
    cleanup();
  });

  it("names a full delete only when the preview says delete_all", async () => {
    vi.mocked(previewEntityPublish).mockResolvedValue({
      incompatible_write_nodes: [],
      change_log_effect: "delete_all",
    });
    renderConfirm();
    expect(
      await screen.findByText("This publish will delete every change entry."),
    ).toBeTruthy();
    expect(
      screen.queryByText(
        "This publish will delete change entries already past the new retention.",
      ),
    ).toBeNull();
  });

  it("names a past-retention delete only when the preview says delete_expired", async () => {
    vi.mocked(previewEntityPublish).mockResolvedValue({
      incompatible_write_nodes: [],
      change_log_effect: "delete_expired",
    });
    renderConfirm();
    expect(
      await screen.findByText(
        "This publish will delete change entries already past the new retention.",
      ),
    ).toBeTruthy();
    expect(
      screen.queryByText("This publish will delete every change entry."),
    ).toBeNull();
  });

  it("adds no change-entry sentence when the preview says none", async () => {
    vi.mocked(previewEntityPublish).mockResolvedValue({
      incompatible_write_nodes: [],
      change_log_effect: "none",
    });
    renderConfirm();
    await screen.findByText("No incompatible write nodes");
    await waitFor(() => {
      expect(screen.queryByText(/change entry/i)).toBeNull();
    });
    expect(screen.getByText(/Rows stay on the previous table/)).toBeTruthy();
  });
});
