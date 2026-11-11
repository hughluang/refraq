/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import en from "@/locales/en-US/common.json";
import { ConsoleNotifications } from "@/providers/notification-provider";

const copy = en as Record<string, string>;
const listSubjectAttributes = vi.hoisted(() => vi.fn());
const createSubjectAttribute = vi.hoisted(() => vi.fn());

vi.mock("@/features/subjects/api", () => ({
  listSubjectAttributes: (...args: unknown[]) => listSubjectAttributes(...args),
  createSubjectAttribute: (...args: unknown[]) => createSubjectAttribute(...args),
  deleteSubjectAttribute: vi.fn(),
  patchSubjectAttribute: vi.fn(),
}));

vi.mock("@/features/branding/BrandingProvider", () => ({
  useBranding: () => ({ brandName: "Refraq" }),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/console/subject-attributes",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) =>
    createElement("a", { href }, children),
  useLinkStatus: () => ({ pending: false }),
}));

vi.mock("@refinedev/core", () => ({
  matchResourceFromRoute: () => ({ found: false }),
  useTranslate: () => (key: string, options?: Record<string, unknown>) => {
    const template = copy[key] ?? key;
    if (!options) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) =>
      String(options[name] ?? ""),
    );
  },
  useNotification: () => ({ open: vi.fn() }),
  useCan: () => ({ data: { can: true } }),
  useBreadcrumb: () => ({ breadcrumbs: [] }),
  CanAccess: ({ children }: { children?: ReactNode }) => children,
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
  if (document.fonts == null) {
    Object.defineProperty(document, "fonts", {
      configurable: true,
      value: { addEventListener() {}, removeEventListener() {} },
    });
  }
}

function resetNotifications() {
  const state = notificationsStore.getState();
  for (const item of [...state.notifications, ...state.queue]) {
    notifications.hide(item.id);
  }
  notifications.clean();
}

function shell(node: ReactNode) {
  return createElement(
    MantineProvider,
    { env: "test" },
    createElement(ConsoleNotifications),
    node,
  );
}

function emptyPage() {
  return { items: [], total: 0, limit: 50, offset: 0 };
}

function rejection(details: { field: string; message: string }[]) {
  return new ApiError(422, "REQUEST_INVALID", "Request validation failed", "req-attr", {}, details);
}

async function openAndSave() {
  fireEvent.click(screen.getAllByRole("button", { name: copy["subjectAttributes.create"] })[0]);
  const dialog = await screen.findByRole("dialog", { name: copy["subjectAttributes.create"] });
  fireEvent.change(within(dialog).getByRole("textbox", { name: "Key" }), {
    target: { value: "region" },
  });
  fireEvent.change(within(dialog).getByRole("textbox", { name: "Name" }), {
    target: { value: "Region" },
  });
  fireEvent.click(within(dialog).getByRole("button", { name: copy["subjectAttributes.save"] }));
}

async function renderList() {
  const { SubjectAttributeList } = await import("@/features/subjects/SubjectAttributeList");
  render(shell(createElement(SubjectAttributeList)));
}

describe("SubjectAttributeList save", () => {
  beforeEach(() => {
    stubDomApis();
    listSubjectAttributes.mockReset();
    listSubjectAttributes.mockResolvedValue(emptyPage());
    createSubjectAttribute.mockReset();
    resetNotifications();
  });

  afterEach(() => {
    cleanup();
    resetNotifications();
  });

  it("marks the mapped field, notifies once, and keeps the dialog free of an alert", async () => {
    createSubjectAttribute.mockRejectedValue(
      rejection([
        { field: "name", message: "Name is taken" },
        { field: "retired", message: "Unknown field" },
      ]),
    );
    await renderList();
    await openAndSave();

    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    const dialog = screen.getByRole("dialog", { name: copy["subjectAttributes.create"] });
    expect(dialog.querySelector("[role='alert']")).toBeNull();
    expect((await screen.findAllByText("Name is taken")).length).toBeGreaterThan(0);
    fireEvent.click(screen.getByText(copy["form.error.details"]));
    const disclosure = screen.getByText(copy["form.error.details"]).closest("details");
    expect(disclosure?.textContent).toContain("retired: Unknown field");
    expect(disclosure?.textContent).not.toContain("Name is taken");
    expect(dialog.textContent).not.toContain("Unknown field");
    expect(dialog.textContent).not.toContain("Request validation failed");
  });

  it("marks every mapped field and sends no notification when the 422 is fully mapped", async () => {
    createSubjectAttribute.mockRejectedValue(
      rejection([{ field: "name", message: "Name is taken" }]),
    );
    await renderList();
    await openAndSave();

    expect((await screen.findAllByText("Name is taken")).length).toBeGreaterThan(0);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(
      screen
        .getByRole("dialog", { name: copy["subjectAttributes.create"] })
        .querySelector("[role='alert']"),
    ).toBeNull();
    expect(screen.queryByText(copy["form.error.details"])).toBeNull();
  });
});
