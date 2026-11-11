/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { SystemParameter } from "@/features/settings/types";
import en from "@/locales/en-US/common.json";
import zh from "@/locales/zh-CN/common.json";
import { ConsoleNotifications } from "@/providers/notification-provider";

const copy = en as Record<string, string>;
const chinese = zh as Record<string, string>;

const api = vi.hoisted(() => vi.fn());
const access = vi.hoisted(() => ({ canWrite: true }));
const notify = vi.hoisted(() => ({ open: vi.fn() }));
const router = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
  refresh: vi.fn(),
}));

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

vi.mock("next/navigation", () => ({
  usePathname: () => "/console/settings",
  useRouter: () => router,
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/features/branding/BrandingProvider", () => ({
  useBranding: () => ({ brandName: "Refraq" }),
}));

const SESSION_LABEL = "settings.parameter.admin_session_ttl_hours.label";
const LOST_LABEL = "settings.parameter.job_lost_detection_sec.label";

function parameter(overrides: Partial<SystemParameter>): SystemParameter {
  return {
    key: "admin_session_ttl_hours",
    value: 24,
    seed: 24,
    source: "seed",
    constraint: { type: "integer", minimum: 1, maximum: 168 },
    group: "session",
    operator_action_required: false,
    label_key: SESSION_LABEL,
    help_key: "settings.parameter.admin_session_ttl_hours.help",
    apply_note_key: "settings.parameter.admin_session_ttl_hours.apply",
    updated_at: null,
    updated_by_user_id: null,
    updated_by_account: null,
    ...overrides,
  };
}

const clampedHours = parameter({ value: 0, source: "user" });
const healthyDetection = parameter({
  key: "job_lost_detection_sec",
  value: 60,
  seed: 60,
  constraint: { type: "integer", minimum: 15, maximum: 3600 },
  group: "jobs",
  label_key: LOST_LABEL,
  help_key: "settings.parameter.job_lost_detection_sec.help",
  apply_note_key: "settings.parameter.job_lost_detection_sec.apply",
});

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

function installApi(
  handler: (path: string, options?: { method?: string }) => Promise<unknown>,
) {
  api.mockImplementation((path: string, options?: { method?: string }) => {
    if (path === "/time-zones") {
      return Promise.resolve({ items: [{ id: "UTC", aliases: [] }] });
    }
    return handler(path, options);
  });
}

async function renderPanel() {
  const { SettingsPanel } = await import("@/features/settings/SettingsPanel");
  render(shell(createElement(SettingsPanel)));
  expect(await screen.findByRole("heading", { name: copy["settings.title"] })).toBeTruthy();
}

function badgeRoot(label: string): HTMLElement {
  const root = screen.getByText(label).parentElement;
  if (!root) throw new Error("missing badge");
  return root;
}

describe("SettingsPanel clamped rows", () => {
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

  it("names the clamped badge in both locales", () => {
    expect(copy["settings.clamped.badge"]).toBe("Clamped");
    expect(chinese["settings.clamped.badge"]).toBe("\u5df2\u94b3\u5236");
  });

  it("shows a clamped badge whose tooltip states the effective value", async () => {
    installApi((path) => {
      if (path === "/settings") {
        return Promise.resolve({ parameters: [clampedHours, healthyDetection] });
      }
      return Promise.reject(new Error(`unexpected ${path}`));
    });
    await renderPanel();
    expect(await screen.findByText(copy[SESSION_LABEL])).toBeTruthy();
    expect(screen.getByText(copy[LOST_LABEL])).toBeTruthy();

    expect(screen.queryByRole("alert")).toBeNull();
    expect(screen.queryByText(copy["settings.clamped.title"])).toBeNull();
    expect(screen.getAllByText(copy["settings.clamped.badge"])).toHaveLength(1);
    fireEvent.mouseEnter(badgeRoot(copy["settings.clamped.badge"]));
    expect(screen.getByRole("tooltip").textContent).toBe(
      "The running value is 1. Reset or save a value the constraint accepts to clear this.",
    );
  });
});

describe("SettingsPanel save and load", () => {
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

  it("notifies once and carries unmapped details when a save is rejected", async () => {
    const { ApiError } = await import("@/lib/api");
    installApi((path, options) => {
      if (path === "/settings" && options?.method === "PATCH") {
        return Promise.reject(
          new ApiError(
            422,
            "REQUEST_INVALID",
            "Request validation failed",
            "req-settings",
            {},
            [
              {
                field: "admin_session_ttl_hours",
                message: "Hours are outside the published range",
              },
            ],
          ),
        );
      }
      if (path === "/settings") {
        return Promise.resolve({ parameters: [parameter({})] });
      }
      return Promise.reject(new Error(`unexpected ${path}`));
    });
    await renderPanel();
    const input = await screen.findByRole("textbox", { name: copy[SESSION_LABEL] });
    fireEvent.keyDown(input, { key: "ArrowUp" });
    fireEvent.click(screen.getByRole("button", { name: copy["settings.save"] }));

    const alerts = await screen.findAllByRole("alert");
    expect(alerts).toHaveLength(1);
    const scroll = document.querySelector("[data-page-scroll]");
    expect(scroll?.querySelector("[role='alert']")).toBeNull();
    expect(scroll?.textContent).not.toContain("Hours are outside the published range");
    expect(alerts[0].textContent).toContain(
      "admin_session_ttl_hours: Hours are outside the published range",
    );
    expect(alerts[0].textContent).toContain("req-settings");
    expect(screen.queryByRole("button", { name: copy["common.retry"] })).toBeNull();
  });

  it("shows unloaded and one retry notification when settings fail to load", async () => {
    const { ApiError } = await import("@/lib/api");
    let calls = 0;
    installApi((path) => {
      if (path !== "/settings") return Promise.reject(new Error(`unexpected ${path}`));
      calls += 1;
      if (calls === 1) {
        return Promise.reject(
          new ApiError(500, "NO_SUCH_CODE", "Raw English detail", "req-settings"),
        );
      }
      return Promise.resolve({ parameters: [parameter({})] });
    });
    await renderPanel();

    const status = await screen.findByRole("button", { name: copy["status.unloaded"] });
    const scroll = document.querySelector("[data-page-scroll]");
    expect(scroll?.contains(status)).toBe(true);
    expect(scroll?.querySelector("[role='alert']")).toBeNull();
    expect(scroll?.textContent).not.toContain("req-settings");
    expect(scroll?.textContent).not.toContain("Raw English detail");
    const alerts = screen.getAllByRole("alert");
    expect(alerts).toHaveLength(1);
    expect(alerts[0].textContent).toContain(copy["problems.unknown"]);
    expect(alerts[0].textContent).toContain("req-settings");

    fireEvent.click(screen.getByRole("button", { name: copy["common.retry"] }));
    expect(await screen.findByText(copy[SESSION_LABEL])).toBeTruthy();
    expect(screen.queryByRole("button", { name: copy["status.unloaded"] })).toBeNull();
    expect(calls).toBe(2);
  });
});
