/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { notifications, notificationsStore } from "@mantine/notifications";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api";
import type { InboundCredential } from "@/features/inbound-credentials/types";
import { ConsoleNotifications } from "@/providers/notification-provider";

const getInboundCredential = vi.hoisted(() => vi.fn());
const createInboundCredential = vi.hoisted(() => vi.fn());
const patchInboundCredential = vi.hoisted(() => vi.fn());

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) => key,
  useCan: () => ({ data: { can: true } }),
  useNotification: () => ({ open: vi.fn() }),
  useBreadcrumb: () => ({ breadcrumbs: [] }),
}));

vi.mock("@/features/inbound-credentials/api", () => ({
  getInboundCredential,
  createInboundCredential,
  patchInboundCredential,
  deleteInboundCredential: vi.fn(),
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children?: ReactNode }) =>
    createElement("a", { href }, children),
  useLinkStatus: () => ({ pending: false }),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/console/inbound-credentials/icr_0123456789ab",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/features/branding/BrandingProvider", () => ({
  useBranding: () => ({ brandName: "Refraq" }),
}));

vi.mock("@/providers/session-store", () => ({
  useSessionStore: (selector: (state: { user: null }) => unknown) => selector({ user: null }),
}));

const TOKEN: InboundCredential = {
  id: "icr_0123456789ab",
  name: "Partner hook",
  type: "token",
  config: { location: "header", name: "X-Hook-Token" },
  created_at: "2026-10-01T02:00:00Z",
  updated_at: "2026-10-20T02:00:00Z",
};

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

function rejected(requestId: string) {
  return new ApiError(500, "NO_SUCH_CODE", "Raw English detail", requestId);
}

describe("InboundCredentialRecord failures", () => {
  beforeEach(() => {
    stubDomApis();
    getInboundCredential.mockReset();
    createInboundCredential.mockReset();
    patchInboundCredential.mockReset();
    resetNotifications();
  });

  afterEach(() => {
    cleanup();
    resetNotifications();
  });

  it("keeps the header, shows unloaded, and notifies once with retry and the request id", async () => {
    getInboundCredential.mockRejectedValueOnce(rejected("req-load"));
    getInboundCredential.mockResolvedValueOnce({ inbound_credential: TOKEN });
    const { InboundCredentialRecord } = await import(
      "@/features/inbound-credentials/InboundCredentialRecord"
    );
    render(
      shell(
        createElement(InboundCredentialRecord, { mode: "show", credentialId: TOKEN.id }),
      ),
    );

    const heading = await screen.findByRole("heading", { name: "inboundCredentials.title" });
    expect(document.querySelector("[data-page-header]")?.contains(heading)).toBe(true);
    const status = screen.getByRole("button", { name: "status.unloaded" });
    const scroll = document.querySelector("[data-page-scroll]");
    expect(scroll?.contains(status)).toBe(true);
    expect(scroll?.querySelector("[role='alert']")).toBeNull();
    expect(scroll?.textContent).not.toContain("req-load");
    expect(screen.queryByText("common.error")).toBeNull();
    const alerts = screen.getAllByRole("alert");
    expect(alerts).toHaveLength(1);
    expect(alerts[0].textContent).toContain("problems.unknown");
    expect(alerts[0].textContent).toContain("common.requestId");
    expect(alerts[0].textContent).toContain("req-load");

    fireEvent.click(screen.getByRole("button", { name: "common.retry" }));
    expect(await screen.findByRole("heading", { name: TOKEN.name })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "status.unloaded" })).toBeNull();
    expect(getInboundCredential).toHaveBeenCalledTimes(2);
    expect(getInboundCredential).toHaveBeenNthCalledWith(1, TOKEN.id);
    expect(getInboundCredential).toHaveBeenNthCalledWith(2, TOKEN.id);
  });

  it("shows one error notification and no form alert when create is rejected", async () => {
    createInboundCredential.mockRejectedValue(rejected("req-create"));
    const { InboundCredentialRecord } = await import(
      "@/features/inbound-credentials/InboundCredentialRecord"
    );
    render(shell(createElement(InboundCredentialRecord, { mode: "create" })));
    fireEvent.change(screen.getByLabelText("inboundCredentials.fields.name"), {
      target: { value: "Partner hook" },
    });
    fireEvent.change(screen.getByLabelText("inboundCredentials.fields.parameterName"), {
      target: { value: "X-Hook-Token" },
    });
    fireEvent.change(screen.getByLabelText("inboundCredentials.fields.secret"), {
      target: { value: "secret" },
    });
    fireEvent.submit(
      document.getElementById("inbound-credential-record-form") as HTMLFormElement,
    );

    const alerts = await screen.findAllByRole("alert");
    expect(alerts).toHaveLength(1);
    const form = document.getElementById("inbound-credential-record-form");
    expect(form?.querySelector("[role='alert']")).toBeNull();
    expect(alerts[0].textContent).toContain("problems.unknown");
    expect(alerts[0].textContent).toContain("common.requestId");
    expect(alerts[0].textContent).toContain("req-create");
    expect(screen.queryByRole("button", { name: "common.retry" })).toBeNull();
  });

  it("shows one error notification and no form alert when the edit save is rejected", async () => {
    getInboundCredential.mockResolvedValue({ inbound_credential: TOKEN });
    patchInboundCredential.mockRejectedValue(rejected("req-edit"));
    const { InboundCredentialRecord } = await import(
      "@/features/inbound-credentials/InboundCredentialRecord"
    );
    render(
      shell(
        createElement(InboundCredentialRecord, { mode: "edit", credentialId: TOKEN.id }),
      ),
    );
    expect(await screen.findByDisplayValue(TOKEN.name)).toBeTruthy();
    fireEvent.submit(
      document.getElementById("inbound-credential-record-form") as HTMLFormElement,
    );

    const alerts = await screen.findAllByRole("alert");
    expect(alerts).toHaveLength(1);
    const form = document.getElementById("inbound-credential-record-form");
    expect(form?.querySelector("[role='alert']")).toBeNull();
    expect(alerts[0].textContent).toContain("req-edit");
    expect(screen.queryByRole("button", { name: "common.retry" })).toBeNull();
  });
});
