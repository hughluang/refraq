/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const copy = vi.hoisted(() => ({
  text: vi.fn(async () => {}),
}));

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) =>
    (
      {
        "layout.leave.title": "Discard unsaved changes?",
        "layout.leave.stay": "Stay",
        "layout.leave.discard": "Discard",
        "common.copy.success": "Copied",
        "tokens.secret.title": "Token secret",
        "tokens.secret.warning": "Copy this secret now.",
        "tokens.secret.copy": "Copy",
        "tokens.secret.done": "Done",
      } as Record<string, string>
    )[key] ?? key,
  useNotification: () => ({ open: vi.fn() }),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/console/account",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/lib/copy-text", () => ({
  copyText: (value: string) => copy.text(value),
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

function shell(node: ReactNode) {
  return createElement(MantineProvider, { env: "test" }, node);
}

describe("PAT secret reveal", () => {
  beforeEach(() => {
    stubDomApis();
    copy.text.mockReset();
    copy.text.mockResolvedValue(undefined);
  });

  afterEach(async () => {
    cleanup();
    const guard = await import("@/components/navigation/leaveGuard");
    if (guard.leavePromptOpen()) guard.settleLeavePrompt(false);
    guard.releaseLeaveGuardSuppression();
  });

  it("asks before closing an uncopied secret and not after it is copied", async () => {
    const { SecretRevealDialog } = await import("@/features/tokens/SecretRevealDialog");
    const { LeaveGuardProvider } = await import("@/components/navigation/leaveGuard");
    const onClose = vi.fn();

    render(
      shell(
        createElement(
          LeaveGuardProvider,
          null,
          createElement(SecretRevealDialog, { secret: "pat-secret-value", onClose }),
        ),
      ),
    );

    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(await screen.findByText("Discard unsaved changes?")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Stay" }));
    await waitFor(() => {
      expect(screen.queryByText("Discard unsaved changes?")).toBeNull();
    });
    expect(onClose).not.toHaveBeenCalled();
    expect(screen.queryByText("pat-secret-value")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Copy" }));
    await waitFor(() => {
      expect(copy.text).toHaveBeenCalledWith("pat-secret-value");
    });

    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => {
      expect(onClose).toHaveBeenCalledTimes(1);
    });
    expect(screen.queryByText("Discard unsaved changes?")).toBeNull();
  });

  it("asks on Escape before the secret is copied", async () => {
    const { SecretRevealDialog } = await import("@/features/tokens/SecretRevealDialog");
    const { LeaveGuardProvider } = await import("@/components/navigation/leaveGuard");
    const onClose = vi.fn();

    render(
      shell(
        createElement(
          LeaveGuardProvider,
          null,
          createElement(SecretRevealDialog, { secret: "pat-secret-value", onClose }),
        ),
      ),
    );

    act(() => {
      document.body.dispatchEvent(
        new KeyboardEvent("keydown", { key: "Escape", bubbles: true, cancelable: true }),
      );
    });
    expect(await screen.findByText("Discard unsaved changes?")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Discard" }));
    await waitFor(() => {
      expect(onClose).toHaveBeenCalledTimes(1);
    });
  });
});
