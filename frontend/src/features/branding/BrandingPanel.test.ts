/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en-US/common.json";
import { ConsoleNotifications } from "@/providers/notification-provider";

const copy = en as Record<string, string>;

const api = vi.hoisted(() => vi.fn());
const access = vi.hoisted(() => ({ canWrite: true }));
const notify = vi.hoisted(() => ({ open: vi.fn() }));

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    apiClient: (...args: unknown[]) => api(...args),
  };
});

vi.mock("@refinedev/core", async () => {
  const { default: messages } = await import("@/locales/en-US/common.json");
  const catalog = messages as Record<string, string>;
  const translate = (key: string, options?: Record<string, unknown>) => {
    const template = catalog[key] ?? key;
    if (!options) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) =>
      String(options[name] ?? ""),
    );
  };
  return {
    matchResourceFromRoute: () => ({ found: false }),
    useTranslate: () => translate,
    useNotification: () => notify,
    useCan: () => ({ data: { can: access.canWrite } }),
    useBreadcrumb: () => ({ breadcrumbs: [] }),
  };
});

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children?: ReactNode }) =>
    createElement("a", { href }, children),
  useLinkStatus: () => ({ pending: false }),
}));

const router = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
  refresh: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/console/branding",
  useRouter: () => router,
  useSearchParams: () => new URLSearchParams(),
}));

const replaceBranding = vi.hoisted(() => vi.fn());

vi.mock("@/features/branding/BrandingProvider", () => ({
  useBranding: () => ({
    brandName: "Refraq",
    replaceBranding,
  }),
}));

const LOW_CONTRAST = "#228be6";
const SUFFICIENT_CONTRAST = "#12b886";

function branding(primaryColor: string | null) {
  return {
    brand_names: { "en-US": "Acme" },
    taglines: {},
    primary_color: primaryColor,
    primary_shades: null,
    show_logo: true,
    show_brand_name_with_logo: true,
    logo_url: null,
    favicon_url: null,
    logo_source: null,
    favicon_source: null,
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

async function renderPanel() {
  const { BrandingPanel } = await import("@/features/branding/BrandingPanel");
  render(shell(createElement(BrandingPanel)));
  expect(await screen.findByRole("heading", { name: copy["branding.title"] })).toBeTruthy();
}

function ratioText(ratio: string) {
  return copy["branding.contrast.ratio"].replace("{{ratio}}", ratio);
}

describe("BrandingPanel contrast", () => {
  beforeEach(() => {
    stubDomApis();
    access.canWrite = true;
    api.mockReset();
    notify.open.mockReset();
    resetNotifications();
  });

  afterEach(() => {
    cleanup();
    resetNotifications();
  });

  it("warns on the color field when the custom color is low contrast", async () => {
    api.mockResolvedValue(branding(LOW_CONTRAST));
    await renderPanel();
    expect(await screen.findByText(ratioText("3.56"))).toBeTruthy();

    expect(screen.queryByRole("alert")).toBeNull();
    const mark = screen.getByRole("button", {
      name: `${copy["branding.fields.color"]} ${copy["form.field.status"]}`,
    });
    const colorLabel = screen.getByText(copy["branding.fields.color"]);
    expect(colorLabel.parentElement?.contains(mark)).toBe(true);
    expect(screen.getByText(copy["branding.contrast.title"])).toBeTruthy();
    expect(screen.getByText(copy["branding.contrast.body"])).toBeTruthy();
  });

  it("warns on the read-only color field when the custom color is low contrast", async () => {
    access.canWrite = false;
    api.mockResolvedValue(branding(LOW_CONTRAST));
    await renderPanel();
    expect(await screen.findByText(ratioText("3.56"))).toBeTruthy();

    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByRole("textbox", { name: copy["branding.fields.color"] })).toBeNull();
    const mark = screen.getByRole("button", {
      name: `${copy["branding.fields.color"]} ${copy["form.field.status"]}`,
    });
    const colorLabel = screen.getByText(copy["branding.fields.color"]);
    expect(colorLabel.parentElement?.contains(mark)).toBe(true);
    expect(screen.getByText(LOW_CONTRAST)).toBeTruthy();
    expect(screen.getByText(copy["branding.contrast.title"])).toBeTruthy();
    expect(screen.getByText(copy["branding.contrast.body"])).toBeTruthy();
  });

  it("keeps the ratio and omits the warning when contrast is sufficient", async () => {
    api.mockResolvedValue(branding(SUFFICIENT_CONTRAST));
    await renderPanel();
    expect(await screen.findByText(ratioText("13.28"))).toBeTruthy();
    expect(screen.queryByText(copy["branding.contrast.title"])).toBeNull();
    expect(
      screen.queryByRole("button", {
        name: `${copy["branding.fields.color"]} ${copy["form.field.status"]}`,
      }),
    ).toBeNull();
  });
});

describe("BrandingPanel save, load, and reset", () => {
  beforeEach(() => {
    stubDomApis();
    access.canWrite = true;
    api.mockReset();
    notify.open.mockReset();
    resetNotifications();
  });

  afterEach(() => {
    cleanup();
    resetNotifications();
  });

  it("notifies once when a save failure is not fully mapped", async () => {
    const { ApiError } = await import("@/lib/api");
    api.mockImplementation((path: string, options?: { method?: string }) => {
      if (path === "/branding" && options?.method === "PUT") {
        return Promise.reject(
          new ApiError(
            422,
            "REQUEST_INVALID",
            "Request validation failed",
            "req-brand",
            {},
            [
              { field: "primaryColor", message: "Color is not a brand hex" },
              { field: "retired", message: "Unknown branding field" },
            ],
          ),
        );
      }
      if (path === "/branding") return Promise.resolve(branding(SUFFICIENT_CONTRAST));
      return Promise.reject(new Error(`unexpected ${path}`));
    });
    await renderPanel();
    expect(await screen.findByText(ratioText("13.28"))).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: copy["branding.save"] }));

    const alerts = await screen.findAllByRole("alert");
    expect(alerts).toHaveLength(1);
    const scroll = document.querySelector("[data-page-scroll]");
    expect(scroll?.querySelector("[role='alert']")).toBeNull();
    expect(await screen.findByText("Color is not a brand hex")).toBeTruthy();
    fireEvent.click(screen.getByText(copy["form.error.details"]));
    const disclosure = screen.getByText(copy["form.error.details"]).closest("details");
    expect(disclosure?.textContent).toContain("retired: Unknown branding field");
    expect(disclosure?.textContent).not.toContain("Color is not a brand hex");
    expect(scroll?.textContent).not.toContain("Unknown branding field");
    expect(scroll?.textContent).not.toContain("Request validation failed");
    expect(screen.queryByRole("button", { name: copy["common.retry"] })).toBeNull();
  });

  it("shows unloaded and one retry notification when branding fails to load", async () => {
    const { ApiError } = await import("@/lib/api");
    let calls = 0;
    api.mockImplementation((path: string) => {
      if (path === "/time-zones") {
        return Promise.resolve({ items: [{ id: "UTC", aliases: [] }] });
      }
      if (path !== "/branding") {
        return Promise.reject(new Error(`unexpected ${path}`));
      }
      calls += 1;
      if (calls === 1) {
        return Promise.reject(
          new ApiError(500, "NO_SUCH_CODE", "Raw English detail", "req-brand"),
        );
      }
      return Promise.resolve(branding(null));
    });
    await renderPanel();

    const status = await screen.findByRole("button", { name: copy["status.unloaded"] });
    const scroll = document.querySelector("[data-page-scroll]");
    expect(scroll?.contains(status)).toBe(true);
    expect(scroll?.querySelector("[role='alert']")).toBeNull();
    expect(scroll?.textContent).not.toContain("req-brand");
    expect(scroll?.textContent).not.toContain("Raw English detail");
    const alerts = screen.getAllByRole("alert");
    expect(alerts).toHaveLength(1);
    expect(alerts[0].textContent).toContain(copy["problems.unknown"]);
    expect(alerts[0].textContent).toContain("req-brand");

    fireEvent.click(screen.getByRole("button", { name: copy["common.retry"] }));
    expect(await screen.findByText(copy["branding.fields.color"])).toBeTruthy();
    expect(screen.queryByRole("button", { name: copy["status.unloaded"] })).toBeNull();
    expect(calls).toBe(2);
  });

  it("reports reset failure through the existing notification", async () => {
    const { ApiError } = await import("@/lib/api");
    api.mockImplementation((path: string) => {
      if (path === "/branding/reset") {
        return Promise.reject(
          new ApiError(500, "NO_SUCH_CODE", "Raw English detail", "req-reset"),
        );
      }
      if (path === "/branding") return Promise.resolve(branding(null));
      return Promise.reject(new Error(`unexpected ${path}`));
    });
    await renderPanel();
    expect(await screen.findByText(copy["branding.fields.color"])).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: copy["branding.reset"] }));
    const dialog = await screen.findByRole("dialog", {
      name: copy["branding.reset.confirmTitle"],
    });
    fireEvent.click(within(dialog).getByRole("button", { name: copy["branding.reset"] }));

    await waitFor(() => expect(notify.open).toHaveBeenCalled());
    expect(notify.open).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "error",
        message: copy["branding.title"],
        description: copy["problems.unknown"],
      }),
    );
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
