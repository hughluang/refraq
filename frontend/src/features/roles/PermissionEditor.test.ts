/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createElement, useState, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { PermissionCatalogEntry } from "@/features/roles/types";

const catalog: PermissionCatalogEntry[] = [
  { key: "users:read", description: "Read users" },
  { key: "users:write", description: "Write users" },
  { key: "roles:read", description: "Read roles" },
];

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) =>
    (
      {
        "users.title": "Users",
        "roles.title": "Roles",
        "roles.fields.permissions": "Permissions",
        "roles.permissions.filter": "Filter permissions",
        "roles.permissions.selectAll": "Select all in this group",
        "recordReference.copy": "Copy {{value}}",
        "common.copy.success": "Copied",
        "common.copy.failed": "Copy failed",
      } as Record<string, string>
    )[key] ?? key,
  useNotification: () => ({ open: vi.fn() }),
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
}

function shell(node: ReactNode) {
  return createElement(MantineProvider, { env: "test" }, node);
}

describe("permission editor", () => {
  beforeEach(() => {
    stubDomApis();
  });

  afterEach(() => {
    cleanup();
  });

  it("groups permissions, filters in place, and selects a group", async () => {
    const { PermissionEditor } = await import("@/features/roles/PermissionEditor");
    function Live() {
      const [selected, setSelected] = useState<string[]>([]);
      return createElement(PermissionEditor, {
        catalog,
        selected,
        locked: false,
        onChange: setSelected,
      });
    }
    render(shell(createElement(Live)));

    expect(screen.getByRole("group", { name: "Users" })).toBeTruthy();
    expect(screen.getByRole("group", { name: "Roles" })).toBeTruthy();

    fireEvent.change(screen.getByRole("textbox", { name: "Filter permissions" }), {
      target: { value: "write" },
    });
    expect(screen.queryByRole("checkbox", { name: "Read users" })).toBeNull();
    expect(screen.getByRole("checkbox", { name: "Write users" })).toBeTruthy();

    fireEvent.change(screen.getByRole("textbox", { name: "Filter permissions" }), {
      target: { value: "" },
    });
    fireEvent.click(screen.getAllByRole("checkbox", { name: "Select all in this group" })[0]!);
    expect((screen.getByRole("checkbox", { name: "Read users" }) as HTMLInputElement).checked).toBe(
      true,
    );
    expect((screen.getByRole("checkbox", { name: "Write users" }) as HTMLInputElement).checked).toBe(
      true,
    );

    fireEvent.click(screen.getByRole("checkbox", { name: "Write users" }));
    const selectAll = screen.getAllByRole("checkbox", {
      name: "Select all in this group",
    })[0] as HTMLInputElement;
    expect(selectAll.indeterminate).toBe(true);
  });

  it("shows a locked role as a read-only list of granted permissions", async () => {
    const { PermissionEditor } = await import("@/features/roles/PermissionEditor");
    render(
      shell(
        createElement(PermissionEditor, {
          catalog,
          selected: ["users:read"],
          locked: true,
          onChange: () => undefined,
        }),
      ),
    );
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(screen.getByText("Read users")).toBeTruthy();
    expect(screen.getByText("users:read")).toBeTruthy();
    expect(screen.queryByText("Write users")).toBeNull();
  });
});
