/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import en from "@/locales/en-US/common.json";
import { ConsoleNotifications } from "@/providers/notification-provider";

const copy = en as Record<string, string>;
const listTokens = vi.hoisted(() => vi.fn());
const createToken = vi.hoisted(() => vi.fn());

vi.mock("@/features/tokens/api", () => ({
  listTokens: (...args: unknown[]) => listTokens(...args),
  createToken: (...args: unknown[]) => createToken(...args),
  deactivateToken: vi.fn(),
  deleteToken: vi.fn(),
  restoreToken: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/console/account",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children: ReactNode }) =>
    createElement("a", { href }, children),
  useLinkStatus: () => ({ pending: false }),
}));

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string, options?: Record<string, unknown>) => {
    const template = copy[key] ?? key;
    if (!options) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) =>
      String(options[name] ?? ""),
    );
  },
  useNotification: () => ({ open: vi.fn() }),
  useCan: () => ({ data: { can: true } }),
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
  return new ApiError(422, "REQUEST_INVALID", "Request validation failed", "req-token", {}, details);
}

async function openAndSave() {
  fireEvent.click(screen.getAllByRole("button", { name: copy["tokens.create"] })[0]);
  fireEvent.change(await screen.findByLabelText(/^Name/), { target: { value: "ci" } });
  fireEvent.click(screen.getByRole("button", { name: copy["tokens.create.submit"] }));
}

async function renderList() {
  const { TokenList } = await import("@/features/tokens/TokenList");
  render(shell(createElement(TokenList)));
}

describe("TokenList save", () => {
  beforeEach(() => {
    stubDomApis();
    listTokens.mockReset();
    listTokens.mockResolvedValue(emptyPage());
    createToken.mockReset();
    resetNotifications();
  });

  afterEach(() => {
    cleanup();
    resetNotifications();
  });

  it("marks the mapped field, notifies once, and keeps the dialog free of an alert", async () => {
    createToken.mockRejectedValue(
      rejection([
        { field: "name", message: "Name is taken" },
        { field: "retired", message: "Unknown field" },
      ]),
    );
    await renderList();
    await openAndSave();

    expect(await screen.findAllByRole("alert")).toHaveLength(1);
    const dialog = screen.getByRole("dialog", { name: copy["tokens.create.title"] });
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
    createToken.mockRejectedValue(rejection([{ field: "name", message: "Name is taken" }]));
    await renderList();
    await openAndSave();

    expect((await screen.findAllByText("Name is taken")).length).toBeGreaterThan(0);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(
      screen.getByRole("dialog", { name: copy["tokens.create.title"] }).querySelector("[role='alert']"),
    ).toBeNull();
    expect(screen.queryByText(copy["form.error.details"])).toBeNull();
  });
});
