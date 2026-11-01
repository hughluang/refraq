/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, render, screen } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import zh from "@/locales/zh-CN/common.json";
import type { InboundCredential } from "@/features/inbound-credentials/types";

const getInboundCredential = vi.hoisted(() => vi.fn());

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) => (zh as Record<string, string>)[key] ?? key,
  useCan: () => ({ data: { can: true } }),
  useNotification: () => ({ open: vi.fn() }),
  useBreadcrumb: () => ({ breadcrumbs: [] }),
}));

vi.mock("@/features/inbound-credentials/api", () => ({
  getInboundCredential,
  createInboundCredential: vi.fn(),
  patchInboundCredential: vi.fn(),
  deleteInboundCredential: vi.fn(),
}));

vi.mock("@/components/navigation/useConsoleNavigation", () => ({
  useConsoleNavigation: () => ({ replace: vi.fn() }),
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

describe("InboundCredentialRecord show copy", () => {
  afterEach(() => {
    cleanup();
    getInboundCredential.mockReset();
  });

  it("states that a secret is saved in the active locale", async () => {
    stubDomApis();
    getInboundCredential.mockResolvedValue({ inbound_credential: TOKEN });
    const { InboundCredentialRecord } = await import(
      "@/features/inbound-credentials/InboundCredentialRecord"
    );
    render(
      createElement(
        MantineProvider,
        { env: "test" },
        createElement(InboundCredentialRecord, { mode: "show", credentialId: TOKEN.id }),
      ),
    );
    const sentence = zh["inboundCredentials.fields.secretSet"];
    expect(sentence).toBeTruthy();
    expect(sentence).not.toBe("inboundCredentials.fields.secretSet");
    expect(await screen.findByText(sentence)).toBeTruthy();
    expect(screen.queryByText("inboundCredentials.fields.secretSet")).toBeNull();
    expect(document.querySelector("input[type='password']")).toBeNull();
  });
});
