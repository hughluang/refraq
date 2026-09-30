/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, render, screen } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getDictionary, listDictionaries } from "@/features/dictionaries/api";
import { DictionarySelect } from "@/features/dictionaries/DictionarySelect";
import type { Dictionary } from "@/features/dictionaries/types";

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) => key,
}));

vi.mock("@/features/dictionaries/api", () => ({
  listDictionaries: vi.fn(),
  getDictionary: vi.fn(),
  createDictionary: vi.fn(),
}));

const LOAD_FAILED = "common.error.loadFailed";
const PREVIEW_EMPTY = "entities.fields.dictionaryPreviewEmpty";

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

function dictionary(entries: Dictionary["entries"]): { dictionary: Dictionary } {
  return {
    dictionary: {
      id: "cl_status",
      name: "order_status",
      display_name: "Order status",
      description: null,
      revision: 1,
      deprecated_at: null,
      entry_count: entries?.length ?? 0,
      entries,
      created_at: "2026-01-01T00:00:00Z",
      updated_at: "2026-01-01T00:00:00Z",
    },
  };
}

function renderSelect() {
  return render(
    createElement(
      MantineProvider,
      { env: "test" },
      createElement(DictionarySelect, {
        editable: true,
        value: "cl_status",
        name: "order_status",
        displayName: "Order status",
        deprecated: false,
        behind: false,
        onChange: () => {},
      }),
    ),
  );
}

describe("DictionarySelect", () => {
  beforeEach(() => {
    stubDomApis();
    vi.mocked(listDictionaries).mockResolvedValue({
      items: [],
      total: 0,
      limit: 200,
      offset: 0,
    });
    vi.mocked(getDictionary).mockResolvedValue(dictionary([]));
  });

  afterEach(() => {
    cleanup();
  });

  it("shows a load failure instead of an empty preview", async () => {
    vi.mocked(listDictionaries).mockRejectedValue(new Error("down"));
    vi.mocked(getDictionary).mockRejectedValue(new Error("down"));
    renderSelect();
    expect((await screen.findAllByText(LOAD_FAILED)).length).toBeGreaterThan(0);
    expect(screen.queryByText(PREVIEW_EMPTY)).toBeNull();
  });

  it("shows the empty preview only after codes load with none active", async () => {
    vi.mocked(getDictionary).mockResolvedValue(
      dictionary([{ code: "open", active: false }]),
    );
    renderSelect();
    expect(await screen.findByText(PREVIEW_EMPTY)).toBeTruthy();
    expect(screen.queryByText(LOAD_FAILED)).toBeNull();
  });
});
