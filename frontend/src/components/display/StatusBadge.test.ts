/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { StatusBadge } from "@/components/display/StatusBadge";
import en from "@/locales/en-US/common.json";
import zh from "@/locales/zh-CN/common.json";
import { resetSessionStoreForTests, useSessionStore, type CurrentUser } from "@/providers/session-store";

const UPDATED_AT = "2026-10-11T06:00:29Z";
const FORMATTED_UPDATE = "10/11/2026, 6:00:29 AM";

const viewer: CurrentUser = {
  id: "usr_1",
  account: "ada",
  display_name: "Ada",
  email: null,
  locale: "en-US",
  display_timezone: "UTC",
  role_id: null,
  role_key: null,
  role_name: null,
  permissions: [],
  identity_source: "local",
};

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string, options?: Record<string, unknown>) => {
    const template =
      key === "status.freshness" ? "Last updated {{time}}" : key;
    if (!options) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) =>
      String(options[name] ?? ""),
    );
  },
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

function badgeRoot(label: string): HTMLElement {
  const root = screen.getByText(label).parentElement;
  if (!root) throw new Error("missing badge");
  return root;
}

function renderBadge(
  props: {
    tone: "running";
    labelKey: string;
    freshness?: { updatedAt: string | null; onRefresh: () => void } | null;
    explanation?: string | null;
  },
) {
  return render(
    createElement(
      MantineProvider,
      { env: "test" },
      createElement(StatusBadge, props),
    ),
  );
}

describe("StatusBadge", () => {
  beforeEach(() => {
    stubDomApis();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () =>
        new Response(JSON.stringify({ items: [{ id: "UTC", aliases: [] }] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );
    useSessionStore.setState({
      user: viewer,
      permissionsReady: true,
      identityError: null,
      signedOutLocally: false,
    });
  });

  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    resetSessionStoreForTests();
  });

  it("shows the translated label for the tone", () => {
    renderBadge({
      tone: "running",
      labelKey: "status.job.running",
    });

    expect(screen.getByText("status.job.running")).toBeTruthy();
    expect(screen.queryByText("running")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("shows a freshness marker with the last update and refreshes on click", () => {
    expect(en["status.freshness"]).toBe("Last updated {{time}}");
    expect(zh["status.freshness"]).toBe("\u4e0a\u6b21\u66f4\u65b0 {{time}}");

    const onRefresh = vi.fn();
    renderBadge({
      tone: "running",
      labelKey: "status.job.running",
      freshness: { updatedAt: UPDATED_AT, onRefresh },
    });

    expect(screen.getByText("status.job.running")).toBeTruthy();
    const marker = screen.getByRole("button", {
      name: `Last updated ${FORMATTED_UPDATE}`,
    });
    fireEvent.mouseEnter(marker);
    expect(screen.getByRole("tooltip").textContent).toBe(
      `Last updated ${FORMATTED_UPDATE}`,
    );
    fireEvent.click(marker);
    expect(onRefresh).toHaveBeenCalledTimes(1);
  });

  it("explains the status in a tooltip separate from the freshness marker", () => {
    const { unmount } = renderBadge({
      tone: "running",
      labelKey: "status.job.running",
      explanation: "The worker stopped answering.",
    });
    fireEvent.mouseEnter(badgeRoot("status.job.running"));
    expect(screen.getByRole("tooltip").textContent).toBe("The worker stopped answering.");
    expect(screen.queryByRole("button")).toBeNull();
    unmount();

    renderBadge({
      tone: "running",
      labelKey: "status.job.running",
      explanation: "The worker stopped answering.",
      freshness: { updatedAt: UPDATED_AT, onRefresh: vi.fn() },
    });
    fireEvent.mouseEnter(badgeRoot("status.job.running"));
    expect(screen.getByRole("tooltip").textContent).toBe("The worker stopped answering.");
    fireEvent.mouseLeave(badgeRoot("status.job.running"));
    fireEvent.mouseEnter(
      screen.getByRole("button", { name: `Last updated ${FORMATTED_UPDATE}` }),
    );
    expect(screen.getByRole("tooltip").textContent).toBe(`Last updated ${FORMATTED_UPDATE}`);
  });
});
