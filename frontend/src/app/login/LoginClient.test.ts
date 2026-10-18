/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const login = vi.hoisted(() => vi.fn());
const probe = vi.hoisted(() => vi.fn());

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) => key,
  useLogin: () => ({ mutate: login, isPending: false }),
}));

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/features/branding/BrandingProvider", () => ({
  useBranding: () => ({
    logoUrl: null,
    brandName: "Refraq",
    tagline: null,
    raw: { show_brand_name_with_logo: true },
  }),
}));

vi.mock("@/providers/auth-provider", () => ({
  probeLoginSession: (...args: unknown[]) => probe(...args),
}));

vi.mock("@/providers/session-store", () => ({
  useSessionStore: (selector: (state: { identityError: null }) => unknown) =>
    selector({ identityError: null }),
}));

vi.mock("@/lib/api", () => ({
  apiClient: () => Promise.resolve({ items: [] }),
  ApiError: class ApiError extends Error {},
}));

vi.mock("@/components/LangSwitcher", () => ({
  LangSwitcher: () => null,
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

function precedes(earlier: Node, later: Node) {
  return Boolean(
    earlier.compareDocumentPosition(later) & Node.DOCUMENT_POSITION_FOLLOWING,
  );
}

describe("login credential failure", () => {
  beforeEach(() => {
    stubDomApis();
    login.mockReset();
    probe.mockReset();
  });

  afterEach(() => {
    cleanup();
  });

  it("shows a skeleton while probing, then the credential error above submit", async () => {
    let settle: (value: "anonymous") => void = () => {};
    probe.mockImplementation(
      () =>
        new Promise<"anonymous">((resolve) => {
          settle = resolve;
        }),
    );
    const { default: LoginPage } = await import("@/app/login/LoginClient");
    render(createElement(MantineProvider, null, createElement(LoginPage)));

    expect(screen.getByLabelText("common.loading").getAttribute("aria-busy")).toBe("true");
    expect(screen.queryByRole("button", { name: "auth.login.submit" })).toBeNull();

    settle("anonymous");
    const submit = await screen.findByRole("button", { name: "auth.login.submit" });
    fireEvent.submit(submit.closest("form") as HTMLFormElement);
    const options = login.mock.calls[0]?.[1] as {
      onSuccess: (result: { success: boolean; error: { message: string } }) => void;
    };
    act(() => {
      options.onSuccess({
        success: false,
        error: { message: "auth.login.error.invalidCredentials" },
      });
    });

    const alert = screen.getByRole("alert");
    expect(alert.textContent).toBe("auth.login.error.invalidCredentials");
    expect(precedes(alert, submit)).toBe(true);
    await waitFor(() => {
      expect(screen.queryByLabelText("common.loading")).toBeNull();
    });
  });
});
