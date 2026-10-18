/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const router = vi.hoisted(() => ({
  push: vi.fn(),
  replace: vi.fn(),
  refresh: vi.fn(),
}));

const linkNav = vi.hoisted(() => ({ proceeded: false }));

vi.mock("next/navigation", () => ({
  usePathname: () => "/console/entities/ent_1",
  useRouter: () => router,
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("next/link", () => ({
  useLinkStatus: () => ({ pending: false }),
  default: ({
    href,
    children,
    onNavigate,
    onClick,
  }: {
    href: string;
    children: ReactNode;
    onNavigate?: (event: { preventDefault: () => void }) => void;
    onClick?: (event: { preventDefault: () => void }) => void;
  }) =>
    createElement(
      "a",
      {
        href,
        onClick: (event: { preventDefault: () => void }) => {
          onClick?.(event);
          let prevented = false;
          onNavigate?.({
            preventDefault() {
              prevented = true;
              event.preventDefault();
            },
          });
          linkNav.proceeded = !prevented;
        },
      },
      children,
    ),
}));

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) =>
    (
      {
        "layout.leave.title": "Discard unsaved changes?",
        "layout.leave.stay": "Stay",
        "layout.leave.discard": "Discard",
      } as Record<string, string>
    )[key] ?? key,
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

function beforeUnloadAdds(spy: { mock: { calls: unknown[][] } }) {
  return spy.mock.calls.filter((call) => call[0] === "beforeunload");
}

describe("console navigation leave guard", () => {
  beforeEach(() => {
    stubDomApis();
    router.push.mockReset();
    router.replace.mockReset();
    linkNav.proceeded = false;
    window.history.pushState(null, "", "/console/entities/ent_1?tab=attributes");
  });

  afterEach(async () => {
    cleanup();
    const guard = await import("@/components/navigation/leaveGuard");
    if (guard.leavePromptOpen()) guard.settleLeavePrompt(false);
    guard.releaseLeaveGuardSuppression();
  });

  async function renderGuard(node: ReactNode) {
    const { LeaveGuardProvider } = await import("@/components/navigation/leaveGuard");
    return render(
      createElement(MantineProvider, null, createElement(LeaveGuardProvider, null, node)),
    );
  }

  it("asks before a dirty hook navigation, stays, or discards", async () => {
    const { useLeaveGuardRegistration } = await import("@/components/navigation/leaveGuard");
    const { useConsoleNavigation } = await import("@/components/navigation/useConsoleNavigation");

    function Probe() {
      useLeaveGuardRegistration(true);
      const { push } = useConsoleNavigation();
      return createElement(
        "button",
        { type: "button", onClick: () => push("/console/users") },
        "Go",
      );
    }

    await renderGuard(createElement(Probe));
    fireEvent.click(screen.getByRole("button", { name: "Go" }));

    expect(await screen.findByRole("dialog")).not.toBeNull();
    expect(screen.getByText("Discard unsaved changes?")).not.toBeNull();
    const stay = screen.getByRole("button", { name: "Stay" });
    const discard = screen.getByRole("button", { name: "Discard" });
    expect(discard.getAttribute("style") ?? "").toContain("red");
    await waitFor(() => {
      expect(document.activeElement).toBe(stay);
    });
    expect(router.push).not.toHaveBeenCalled();

    fireEvent.click(stay);
    await waitFor(() => {
      expect(screen.queryByRole("dialog")).toBeNull();
    });
    expect(router.push).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "Go" }));
    fireEvent.click(await screen.findByRole("button", { name: "Discard" }));
    await waitFor(() => {
      expect(router.push).toHaveBeenCalledWith("/console/users");
    });
  });

  it("cancels a dirty console link until discard", async () => {
    const { useLeaveGuardRegistration } = await import("@/components/navigation/leaveGuard");
    const { ConsoleLink } = await import("@/components/navigation/ConsoleLink");

    function Probe() {
      useLeaveGuardRegistration(true);
      return createElement(ConsoleLink, { href: "/console/users" }, "Users");
    }

    await renderGuard(createElement(Probe));
    fireEvent.click(screen.getByRole("link", { name: "Users" }));
    expect(linkNav.proceeded).toBe(false);
    expect(router.push).not.toHaveBeenCalled();
    fireEvent.click(await screen.findByRole("button", { name: "Stay" }));
    expect(router.push).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("link", { name: "Users" }));
    fireEvent.click(await screen.findByRole("button", { name: "Discard" }));
    await waitFor(() => {
      expect(router.push).toHaveBeenCalledWith("/console/users");
    });
  });

  it("does not guard a query-only change on the same path", async () => {
    const { useLeaveGuardRegistration } = await import("@/components/navigation/leaveGuard");
    const { useConsoleNavigation } = await import("@/components/navigation/useConsoleNavigation");
    const { ConsoleLink } = await import("@/components/navigation/ConsoleLink");

    function Probe() {
      useLeaveGuardRegistration(true);
      const { push } = useConsoleNavigation();
      return createElement(
        "div",
        null,
        createElement(
          "button",
          {
            type: "button",
            onClick: () => push("/console/entities/ent_1?tab=versions"),
          },
          "Push",
        ),
        createElement(
          ConsoleLink,
          { href: "/console/entities/ent_1?tab=access" },
          "Access",
        ),
      );
    }

    await renderGuard(createElement(Probe));
    fireEvent.click(screen.getByRole("button", { name: "Push" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(router.push).toHaveBeenCalledWith("/console/entities/ent_1?tab=versions");

    fireEvent.click(screen.getByRole("link", { name: "Access" }));
    expect(linkNav.proceeded).toBe(true);
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("registers beforeunload only while a registration is dirty", async () => {
    const { useLeaveGuardRegistration } = await import("@/components/navigation/leaveGuard");
    const addSpy = vi.spyOn(window, "addEventListener");

    function Probe({ dirty }: { dirty: boolean }) {
      useLeaveGuardRegistration(dirty);
      return null;
    }

    const view = await renderGuard(createElement(Probe, { dirty: false }));
    expect(beforeUnloadAdds(addSpy)).toHaveLength(0);

    view.rerender(
      createElement(
        MantineProvider,
        null,
        createElement(
          (await import("@/components/navigation/leaveGuard")).LeaveGuardProvider,
          null,
          createElement(Probe, { dirty: true }),
        ),
      ),
    );
    await waitFor(() => {
      expect(beforeUnloadAdds(addSpy).length).toBeGreaterThan(0);
    });

    const blocked = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(blocked);
    expect(blocked.defaultPrevented).toBe(true);

    addSpy.mockClear();
    view.rerender(
      createElement(
        MantineProvider,
        null,
        createElement(
          (await import("@/components/navigation/leaveGuard")).LeaveGuardProvider,
          null,
          createElement(Probe, { dirty: false }),
        ),
      ),
    );
    await waitFor(() => {
      const event = new Event("beforeunload", { cancelable: true });
      window.dispatchEvent(event);
      expect(event.defaultPrevented).toBe(false);
    });
    addSpy.mockRestore();
  });
});
