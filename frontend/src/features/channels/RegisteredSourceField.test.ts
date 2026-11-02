/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  RegisteredSourceField,
  SourceDisplaysProvider,
} from "@/features/channels/RegisteredSourceField";
import { SqlSourceField } from "@/features/channels/SqlSourceField";
import type { SourceDisplay } from "@/features/channels/types";
import { listSources } from "@/features/sources/api/sources";
import type { Source } from "@/features/sources/types";

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) => {
    if (key === "channels.config.source.inaccessible") return "Inaccessible Source";
    if (key === "channels.config.sqlSource.entity") return "Entity database";
    if (key === "channels.config.source.placeholder") return "Select a source";
    if (key === "channels.config.sqlSource.placeholder") return "Select a source";
    return key;
  },
}));

vi.mock("@/features/sources/api/sources", () => ({
  listSources: vi.fn(async () => ({ items: [], total: 0, limit: 100, offset: 0 })),
}));

const MARKER = "Inaccessible Source";

function listed(id: string, name: string, key: string): Source {
  return {
    id,
    key,
    locator_key: key,
    name,
    kind: "database",
    status: "active",
    description: null,
    engine: "postgresql",
    access: null,
    has_access: true,
    access_updated_at: null,
  };
}

function renderField(node: ReactNode) {
  return render(createElement(MantineProvider, { env: "test" }, node));
}

function sourceField(
  value: string,
  displays: readonly SourceDisplay[],
) {
  return createElement(SourceDisplaysProvider, {
    displays,
    children: createElement(RegisteredSourceField, {
      label: "Source",
      description: "Registered Source",
      value,
      editable: true,
      onChange: () => undefined,
    }),
  });
}

describe("registered and SQL source fields", () => {
  beforeEach(() => {
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
        value: { ready: Promise.resolve() },
      });
    }
    vi.mocked(listSources).mockResolvedValue({
      items: [],
      total: 0,
      limit: 100,
      offset: 0,
    });
  });

  afterEach(cleanup);

  it("renders an inaccessible Source as the marker, not its name or id", async () => {
    vi.mocked(listSources).mockResolvedValue({
      items: [listed("src_hidden", "Warehouse secret", "wh-secret")],
      total: 1,
      limit: 100,
      offset: 0,
    });
    renderField(
      sourceField("src_hidden", [{ source_id: "src_hidden", inaccessible: true }]),
    );

    const input = await screen.findByRole("combobox", { name: "Source" });
    await waitFor(() => {
      expect((input as HTMLInputElement).value).toBe(MARKER);
    });
    expect(document.body.textContent).not.toContain("Warehouse secret");
    expect(document.body.textContent).not.toContain("wh-secret");
    expect(document.body.textContent).not.toContain("src_hidden");
  });

  it("uses the readable display name when the Source is absent from the list", async () => {
    renderField(
      sourceField("src_shown", [
        { source_id: "src_shown", key: "shown-key", name: "Shown name" },
      ]),
    );

    await waitFor(() => {
      expect(
        (screen.getByRole("combobox", { name: "Source" }) as HTMLInputElement).value,
      ).toBe("Shown name");
    });
    expect(document.body.textContent).not.toContain("src_shown");
  });

  it("does not fall back to a raw id when no display name is available", async () => {
    renderField(sourceField("src_missing", []));

    await waitFor(() => {
      expect(
        (screen.getByRole("combobox", { name: "Source" }) as HTMLInputElement).value,
      ).toBe(MARKER);
    });
    expect(document.body.textContent).not.toContain("src_missing");
  });

  it("keeps a listed Source name when the reader can see it", async () => {
    vi.mocked(listSources).mockResolvedValue({
      items: [listed("src_wh", "Warehouse", "wh")],
      total: 1,
      limit: 100,
      offset: 0,
    });
    renderField(
      sourceField("src_wh", [{ source_id: "src_wh", key: "wh", name: "Warehouse" }]),
    );

    await waitFor(() => {
      expect(
        (screen.getByRole("combobox", { name: "Source" }) as HTMLInputElement).value,
      ).toBe("Warehouse");
    });
  });

  it("renders an inaccessible SQL source as the marker", async () => {
    vi.mocked(listSources).mockResolvedValue({
      items: [listed("src_hidden", "Warehouse secret", "wh-secret")],
      total: 1,
      limit: 100,
      offset: 0,
    });
    renderField(
      createElement(SourceDisplaysProvider, {
        displays: [{ source_id: "src_hidden", inaccessible: true }],
        children: createElement(SqlSourceField, {
          label: "Source",
          description: "Entity database or a registered Source",
          value: { kind: "source", source_id: "src_hidden" },
          editable: true,
          onChange: () => undefined,
        }),
      }),
    );

    await waitFor(() => {
      expect(
        (screen.getByRole("combobox", { name: "Source" }) as HTMLInputElement).value,
      ).toBe(MARKER);
    });
    expect(document.body.textContent).not.toContain("Warehouse secret");
    expect(document.body.textContent).not.toContain("wh-secret");
    expect(document.body.textContent).not.toContain("src_hidden");
  });

  it("labels the entity database without a Source marker", async () => {
    renderField(
      createElement(SqlSourceField, {
        label: "Source",
        description: "Entity database or a registered Source",
        value: { kind: "entity" },
        editable: true,
        onChange: () => undefined,
      }),
    );

    await waitFor(() => {
      expect(
        (screen.getByRole("combobox", { name: "Source" }) as HTMLInputElement).value,
      ).toBe("Entity database");
    });
    expect(document.body.textContent).not.toContain(MARKER);
  });
});
