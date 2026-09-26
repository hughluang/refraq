/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, render, screen } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AttributeFormApi } from "@/features/entities/AttributeEditor";
import type { AttributeDraft } from "@/features/entities/types";

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) => key,
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

const LONG_ERROR =
  'Attribute name "BadName" must start with a letter and use only a-z, 0-9, and underscore';

function draft(overrides: Partial<AttributeDraft> = {}): AttributeDraft {
  return {
    name: "good_name",
    normalized_type: "string",
    nullable: true,
    unique: false,
    indexed: false,
    description: "",
    ...overrides,
  };
}

function formApi(
  attributes: AttributeDraft[],
  errors: Partial<Record<string, string>> = {},
): AttributeFormApi {
  return {
    values: { attributes },
    getInputProps: (path: string) => {
      const index = Number(path.split(".")[1] ?? 0);
      const attr = attributes[index];
      if (!attr) return {};
      if (path.endsWith(".name")) {
        return { value: attr.name, onChange: () => {}, error: errors[path] };
      }
      if (path.endsWith(".description")) {
        return {
          value: attr.description,
          onChange: () => {},
          error: errors[path],
        };
      }
      if (path.endsWith(".normalized_type")) {
        return {
          value: attr.normalized_type,
          onChange: () => {},
          error: errors[path],
        };
      }
      if (path.endsWith(".nullable")) {
        return { checked: attr.nullable, onChange: () => {} };
      }
      if (path.endsWith(".unique")) {
        return { checked: attr.unique, onChange: () => {} };
      }
      if (path.endsWith(".indexed")) {
        return { checked: attr.indexed, onChange: () => {} };
      }
      return {};
    },
    insertListItem: () => {},
    removeListItem: () => {},
  };
}

describe("AttributeEditor", () => {
  beforeEach(() => {
    stubDomApis();
  });

  afterEach(() => {
    cleanup();
  });

  it("renders long errors under the row so they do not sit inside flex columns", async () => {
    const { AttributeEditor } = await import(
      "@/features/entities/AttributeEditor"
    );

    const { container } = render(
      createElement(
        MantineProvider,
        null,
        createElement(AttributeEditor, {
          editable: true,
          form: formApi([draft({ name: "BadName" })], {
            "attributes.0.name": LONG_ERROR,
            "attributes.0.description":
              "Description field also has a long validation message here",
          }),
        }),
      ),
    );

    const group = container.querySelector(".mantine-Group-root");
    expect(group).not.toBeNull();
    expect(
      (group as HTMLElement).style.getPropertyValue("--group-align") ||
        getComputedStyle(group as Element).alignItems,
    ).toMatch(/flex-start/);

    const textInputs = container.querySelectorAll(".mantine-TextInput-root");
    expect(textInputs.length).toBeGreaterThanOrEqual(2);

    const nameCol = textInputs[0] as HTMLElement;
    const descriptionCol = textInputs[1] as HTMLElement;

    expect(nameCol.style.flex).toBe("1 1 10rem");
    expect(nameCol.style.minWidth).toBe("0px");
    expect(descriptionCol.style.flex).toBe("2 1 12rem");
    expect(descriptionCol.style.minWidth).toBe("0px");

    const typeCol = container.querySelector(
      ".mantine-Select-root",
    ) as HTMLElement | null;
    expect(typeCol).not.toBeNull();
    expect(typeCol?.style.flex).toBe("1 1 9rem");
    expect(typeCol?.style.minWidth).toBe("0px");

    const nameError = screen.getByText(LONG_ERROR);
    const descriptionError = screen.getByText(
      "Description field also has a long validation message here",
    );
    expect(group?.contains(nameError)).toBe(false);
    expect(group?.contains(descriptionError)).toBe(false);
    expect(nameCol.querySelector(".mantine-InputWrapper-error")).toBeNull();
    expect(descriptionCol.querySelector(".mantine-InputWrapper-error")).toBeNull();
  });

  it("applies the same column flex basis when there is no error", async () => {
    const { AttributeEditor } = await import(
      "@/features/entities/AttributeEditor"
    );

    const { container } = render(
      createElement(
        MantineProvider,
        null,
        createElement(AttributeEditor, {
          editable: true,
          form: formApi([draft()]),
        }),
      ),
    );

    const nameCol = container.querySelector(
      ".mantine-TextInput-root",
    ) as HTMLElement;
    expect(nameCol.style.flex).toBe("1 1 10rem");
    expect(nameCol.style.minWidth).toBe("0px");
    expect(container.querySelector(".mantine-InputWrapper-error")).toBeNull();
    expect(screen.queryByText(LONG_ERROR)).toBeNull();
  });

  const columnHeaders = [
    "entities.fields.attributeName",
    "entities.fields.normalizedType",
    "entities.fields.nullable",
    "entities.fields.unique",
    "entities.fields.indexed",
    "entities.fields.attributeDescription",
  ];

  it.each([true, false])(
    "shows each column header once when editable is %s",
    async (editable) => {
      const { AttributeEditor } = await import(
        "@/features/entities/AttributeEditor"
      );

      render(
        createElement(
          MantineProvider,
          null,
          createElement(AttributeEditor, {
            editable,
            form: formApi([draft(), draft({ name: "other_name", nullable: false })]),
          }),
        ),
      );

      for (const header of columnHeaders) {
        const nodes = screen.getAllByText(header);
        expect(nodes).toHaveLength(1);
        expect(nodes[0]?.closest("label")).toBeNull();
      }
    },
  );

  it("names each editable control with its column", async () => {
    const { AttributeEditor } = await import(
      "@/features/entities/AttributeEditor"
    );

    render(
      createElement(
        MantineProvider,
        null,
        createElement(AttributeEditor, {
          editable: true,
          form: formApi([draft(), draft({ name: "other_name" })]),
        }),
      ),
    );

    expect(
      screen.getAllByRole("textbox", { name: "entities.fields.attributeName" }),
    ).toHaveLength(2);
    expect(
      screen.getAllByRole("textbox", {
        name: "entities.fields.attributeDescription",
      }),
    ).toHaveLength(2);
    expect(
      screen.getAllByRole("combobox", { name: "entities.fields.normalizedType" }),
    ).toHaveLength(2);
    expect(
      screen.getAllByRole("switch", { name: "entities.fields.nullable" }),
    ).toHaveLength(2);
    expect(
      screen.getAllByRole("switch", { name: "entities.fields.unique" }),
    ).toHaveLength(2);
    expect(
      screen.getAllByRole("switch", { name: "entities.fields.indexed" }),
    ).toHaveLength(2);
    expect(screen.getAllByRole("button", { name: "actions.delete" })).toHaveLength(
      2,
    );
  });
});
