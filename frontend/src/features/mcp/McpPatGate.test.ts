/**
 * @vitest-environment jsdom
 * @vitest-environment-options {"url": "https://console.example.com/console/mcp/metadata"}
 */

import { MantineProvider } from "@mantine/core";
import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en-US/common.json";
import {
  resetSessionStoreForTests,
  useSessionStore,
  type CurrentUser,
} from "@/providers/session-store";

const copy = en as Record<string, string>;
const getIdentity = vi.hoisted(() => vi.fn(() => ({ data: undefined })));

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) => copy[key] ?? key,
  useNotification: () => ({ open: vi.fn() }),
  useBreadcrumb: () => ({ breadcrumbs: [] }),
  useGetIdentity: () => getIdentity(),
}));

vi.mock("next/link", () => ({
  default: ({ href, children }: { href: string; children?: ReactNode }) =>
    createElement("a", { href }, children),
  useLinkStatus: () => ({ pending: false }),
}));

const pathname = vi.hoisted(() => ({ current: "/console/mcp/metadata" }));

vi.mock("next/navigation", () => ({
  usePathname: () => pathname.current,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), refresh: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("@/features/branding/BrandingProvider", () => ({
  useBranding: () => ({ brandName: "Refraq" }),
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

const PAT = "rfqpat-distinct-secret-04";
const apiBase = process.env.NEXT_PUBLIC_REFRAQ_API_BASE_URL || "/api";

function sessionUser(id: string, account: string, displayName: string): CurrentUser {
  return {
    id,
    account,
    display_name: displayName,
    email: null,
    locale: "en-US",
    display_timezone: null,
    role_id: null,
    role_key: null,
    role_name: null,
    permissions: ["console:access"],
    identity_source: "local",
  };
}

function jsonResponse(status: number, body: unknown) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "Content-Type": status >= 400 ? "application/problem+json" : "application/json",
    },
  });
}

function meBody(id: string, account: string, displayName: string) {
  return {
    user: {
      id,
      account,
      display_name: displayName,
      email: null,
      locale: "zh-CN",
      display_timezone: null,
      role_id: null,
      role_key: null,
      role_name: null,
      permissions: [],
      identity_source: "local",
    },
  };
}

function shell(node: ReactNode) {
  return createElement(MantineProvider, { env: "test" }, node);
}

function authMeCalls() {
  return vi
    .mocked(fetch)
    .mock.calls.filter((call) => String(call[0]).endsWith("/auth/me"));
}

function storageDump(storage: Storage) {
  const values: string[] = [];
  for (let index = 0; index < storage.length; index += 1) {
    const key = storage.key(index);
    if (!key) continue;
    values.push(key, storage.getItem(key) ?? "");
  }
  return values.join("\n");
}

describe("MCP PAT identity gate", () => {
  beforeEach(() => {
    stubDomApis();
    localStorage.clear();
    sessionStorage.clear();
    pathname.current = "/console/mcp/metadata";
    resetSessionStoreForTests();
    getIdentity.mockClear();
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => {
        return new Response(JSON.stringify({ tools: [] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );
  });

  afterEach(() => {
    cleanup();
    resetSessionStoreForTests();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("shows a masked empty User PAT on an endpoint detail page", async () => {
    const { default: Layout } = await import("@/app/console/mcp/layout");
    const { McpMetadataDetail } = await import("@/features/mcp/McpMetadataDetail");
    render(shell(createElement(Layout, null, createElement(McpMetadataDetail))));

    const input = screen.getByLabelText("Personal access token") as HTMLInputElement;
    expect(input.type).toBe("password");
    expect(input.value).toBe("");
    expect(input.autocomplete).toBe("off");
    cleanup();

    pathname.current = "/console/mcp/entity";
    const { McpEntityDetail } = await import("@/features/mcp/McpEntityDetail");
    render(shell(createElement(Layout, null, createElement(McpEntityDetail))));
    const entityInput = screen.getByLabelText("Personal access token") as HTMLInputElement;
    expect(entityInput.type).toBe("password");
    expect(entityInput.value).toBe("");
    expect(entityInput.autocomplete).toBe("off");
  });

  it("shows the signed-in user id and endpoint when that user's PAT is verified", async () => {
    useSessionStore.setState({
      user: sessionUser("user-a", "ada", "Ada"),
      permissionsReady: true,
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (String(url).endsWith("/auth/me")) {
          return jsonResponse(200, meBody("user-a", "other-account", "Pat Owner"));
        }
        return jsonResponse(200, { tools: [] });
      }),
    );
    const openDb = vi.fn();
    vi.stubGlobal("indexedDB", { open: openDb });
    const log = vi.spyOn(console, "log").mockImplementation(() => {});
    const info = vi.spyOn(console, "info").mockImplementation(() => {});
    const warn = vi.spyOn(console, "warn").mockImplementation(() => {});
    const error = vi.spyOn(console, "error").mockImplementation(() => {});
    const debug = vi.spyOn(console, "debug").mockImplementation(() => {});

    const { default: Layout } = await import("@/app/console/mcp/layout");
    const { McpMetadataDetail } = await import("@/features/mcp/McpMetadataDetail");
    render(shell(createElement(Layout, null, createElement(McpMetadataDetail))));

    expect(
      screen.getByText(
        "Verification calls GET /auth/me and records last use of this personal access token.",
      ),
    ).toBeTruthy();
    expect(document.body.textContent).not.toMatch(/side-effect free/i);
    expect(screen.queryByText("Selected endpoint /mcp")).toBeNull();

    const before = authMeCalls().length;
    fireEvent.change(screen.getByLabelText("Personal access token"), { target: { value: PAT } });
    fireEvent.click(screen.getByRole("button", { name: "Verify personal access token" }));

    expect(
      await screen.findByText("This personal access token belongs to the signed-in user. user-a"),
    ).toBeTruthy();
    expect(screen.getByText("Selected endpoint /mcp")).toBeTruthy();
    expect(document.body.textContent).not.toContain("Pat Owner");
    expect(document.body.textContent).not.toContain("other-account");
    expect(document.body.textContent).toContain("Bearer <YOUR_TOKEN>");
    expect(document.body.textContent).not.toContain(PAT);
    for (const link of screen.getAllByRole("link")) {
      expect(link.getAttribute("href") ?? "").not.toContain(PAT);
    }

    const added = authMeCalls().slice(before);
    expect(added).toHaveLength(1);
    expect(String(added[0][0])).toBe(`${apiBase}/auth/me`);
    const init = added[0][1] as RequestInit;
    expect(init.method).toBe("GET");
    expect(init.credentials).toBe("omit");
    expect(init.cache).toBe("no-store");
    const headers = new Headers(init.headers);
    expect(headers.get("Authorization")).toBe(`Bearer ${PAT}`);
    expect(headers.has("Cookie")).toBe(false);
    const urls = vi.mocked(fetch).mock.calls.map((call) => String(call[0]));
    expect(urls.some((url) => url.endsWith("/mcp") || url.endsWith("/mcp/entity"))).toBe(
      false,
    );
    expect(getIdentity).not.toHaveBeenCalled();
    const logged = [log, info, warn, error, debug]
      .flatMap((spy) => spy.mock.calls)
      .flat()
      .map((part) => String(part))
      .join("\n");
    expect(logged).not.toContain(PAT);
    expect(storageDump(localStorage)).not.toContain(PAT);
    expect(storageDump(sessionStorage)).not.toContain(PAT);
    expect(openDb).not.toHaveBeenCalled();
    expect(window.location.href).not.toContain(PAT);
  });

  it("rejects another user's PAT before any MCP request", async () => {
    useSessionStore.setState({
      user: sessionUser("user-a", "ada", "Ada"),
      permissionsReady: true,
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (String(url).endsWith("/auth/me")) {
          return jsonResponse(200, meBody("user-b", "ada", "Ada"));
        }
        return jsonResponse(200, { tools: [] });
      }),
    );

    const { default: Layout } = await import("@/app/console/mcp/layout");
    const { McpMetadataDetail } = await import("@/features/mcp/McpMetadataDetail");
    render(shell(createElement(Layout, null, createElement(McpMetadataDetail))));

    const before = vi.mocked(fetch).mock.calls.length;
    fireEvent.change(screen.getByLabelText("Personal access token"), { target: { value: PAT } });
    fireEvent.click(screen.getByRole("button", { name: "Verify personal access token" }));

    expect(await screen.findByText("This personal access token belongs to a different user.")).toBeTruthy();
    expect(screen.queryByText(/belongs to the signed-in user/)).toBeNull();
    expect(screen.queryByText("user-b")).toBeNull();
    expect(document.body.textContent).not.toContain(PAT);
    const added = vi.mocked(fetch).mock.calls.slice(before).map((call) => String(call[0]));
    expect(added).toEqual([`${apiBase}/auth/me`]);
    expect(useSessionStore.getState().user?.id).toBe("user-a");
    expect(useSessionStore.getState().signedOutLocally).toBe(false);
  });

  it("keeps the Console session when the PAT is invalid", async () => {
    useSessionStore.setState({
      user: sessionUser("user-a", "ada", "Ada"),
      permissionsReady: true,
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (String(url).endsWith("/auth/me")) {
          return jsonResponse(401, {
            type: "urn:refraq:problem:AUTH_PAT_INVALID",
            status: 401,
            detail: "hidden-problem-detail",
            code: "AUTH_PAT_INVALID",
          });
        }
        return jsonResponse(200, { tools: [] });
      }),
    );

    const { default: Layout } = await import("@/app/console/mcp/layout");
    const { McpMetadataDetail } = await import("@/features/mcp/McpMetadataDetail");
    render(shell(createElement(Layout, null, createElement(McpMetadataDetail))));

    const before = vi.mocked(fetch).mock.calls.length;
    fireEvent.change(screen.getByLabelText("Personal access token"), { target: { value: PAT } });
    fireEvent.click(screen.getByRole("button", { name: "Verify personal access token" }));

    expect(
      await screen.findByText(
        "That personal access token was not accepted. The Console session stays signed in.",
      ),
    ).toBeTruthy();
    expect(screen.queryByText(/belongs to the signed-in user/)).toBeNull();
    expect(screen.queryByText(/belongs to a different user/)).toBeNull();
    expect(document.body.textContent).not.toContain("hidden-problem-detail");
    expect(document.body.textContent).not.toContain(PAT);
    expect(useSessionStore.getState().user?.id).toBe("user-a");
    expect(useSessionStore.getState().signedOutLocally).toBe(false);
    expect(window.location.pathname).toBe("/console/mcp/metadata");
    const added = vi.mocked(fetch).mock.calls.slice(before).map((call) => String(call[0]));
    expect(added).toEqual([`${apiBase}/auth/me`]);
  });

  it("keeps the Console session when the PAT check is unauthenticated", async () => {
    useSessionStore.setState({
      user: sessionUser("user-a", "ada", "Ada"),
      permissionsReady: true,
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (String(url).endsWith("/auth/me")) {
          return jsonResponse(401, {
            type: "urn:refraq:problem:AUTH_UNAUTHENTICATED",
            status: 401,
            detail: "Not signed in or session expired",
            code: "AUTH_UNAUTHENTICATED",
          });
        }
        return jsonResponse(200, { tools: [] });
      }),
    );

    const { default: Layout } = await import("@/app/console/mcp/layout");
    const { McpMetadataDetail } = await import("@/features/mcp/McpMetadataDetail");
    render(shell(createElement(Layout, null, createElement(McpMetadataDetail))));

    fireEvent.change(screen.getByLabelText("Personal access token"), { target: { value: PAT } });
    fireEvent.click(screen.getByRole("button", { name: "Verify personal access token" }));

    expect(
      await screen.findByText(
        "That personal access token was not accepted. The Console session stays signed in.",
      ),
    ).toBeTruthy();
    expect(document.body.textContent).not.toContain("Not signed in or session expired");
    expect(document.body.textContent).not.toContain(PAT);
    expect(useSessionStore.getState().user?.id).toBe("user-a");
    expect(useSessionStore.getState().signedOutLocally).toBe(false);
    expect(window.location.pathname).toBe("/console/mcp/metadata");
    const meCall = authMeCalls().at(-1);
    expect(meCall).toBeTruthy();
    expect((meCall?.[1] as RequestInit).credentials).toBe("omit");
  });

  it("clears the verified user when the User PAT changes", async () => {
    useSessionStore.setState({
      user: sessionUser("user-a", "ada", "Ada"),
      permissionsReady: true,
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (String(url).endsWith("/auth/me")) {
          return jsonResponse(200, meBody("user-a", "other-account", "Pat Owner"));
        }
        return jsonResponse(200, { tools: [] });
      }),
    );

    const { default: Layout } = await import("@/app/console/mcp/layout");
    const { McpMetadataDetail } = await import("@/features/mcp/McpMetadataDetail");
    render(shell(createElement(Layout, null, createElement(McpMetadataDetail))));

    fireEvent.change(screen.getByLabelText("Personal access token"), { target: { value: PAT } });
    fireEvent.click(screen.getByRole("button", { name: "Verify personal access token" }));
    expect(
      await screen.findByText("This personal access token belongs to the signed-in user. user-a"),
    ).toBeTruthy();

    const callsAfterVerify = authMeCalls().length;
    fireEvent.change(screen.getByLabelText("Personal access token"), {
      target: { value: `${PAT}-edited` },
    });

    expect(screen.queryByText(/belongs to the signed-in user/)).toBeNull();
    expect(screen.queryByText("user-a")).toBeNull();
    expect(screen.queryByText("Selected endpoint /mcp")).toBeNull();
    expect(authMeCalls()).toHaveLength(callsAfterVerify);
    expect((screen.getByLabelText("Personal access token") as HTMLInputElement).value).toBe(
      `${PAT}-edited`,
    );
  });

  it("keeps the User PAT across endpoint pages and drops it when the workspace unmounts", async () => {
    useSessionStore.setState({
      user: sessionUser("user-a", "ada", "Ada"),
      permissionsReady: true,
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (String(url).endsWith("/auth/me")) {
          return jsonResponse(200, meBody("user-a", "other-account", "Pat Owner"));
        }
        return jsonResponse(200, { tools: [] });
      }),
    );

    const { default: Layout } = await import("@/app/console/mcp/layout");
    const { McpMetadataDetail } = await import("@/features/mcp/McpMetadataDetail");
    const { McpEntityDetail } = await import("@/features/mcp/McpEntityDetail");
    const view = render(
      shell(createElement(Layout, null, createElement(McpMetadataDetail))),
    );

    fireEvent.change(screen.getByLabelText("Personal access token"), { target: { value: PAT } });
    fireEvent.click(screen.getByRole("button", { name: "Verify personal access token" }));
    expect(
      await screen.findByText("This personal access token belongs to the signed-in user. user-a"),
    ).toBeTruthy();

    pathname.current = "/console/mcp/entity";
    view.rerender(shell(createElement(Layout, null, createElement(McpEntityDetail))));

    expect((screen.getByLabelText("Personal access token") as HTMLInputElement).value).toBe(PAT);
    expect(
      screen.getByText("This personal access token belongs to the signed-in user. user-a"),
    ).toBeTruthy();
    expect(screen.getByText("Selected endpoint /mcp/entity")).toBeTruthy();
    expect(screen.queryByText("Selected endpoint /mcp")).toBeNull();
    expect(document.body.textContent).toContain("Bearer <YOUR_TOKEN>");
    expect(document.body.textContent).not.toContain(PAT);

    view.unmount();
    pathname.current = "/console/mcp/metadata";
    render(shell(createElement(Layout, null, createElement(McpMetadataDetail))));
    expect((screen.getByLabelText("Personal access token") as HTMLInputElement).value).toBe("");
    expect(screen.queryByText(/belongs to the signed-in user/)).toBeNull();
    expect(storageDump(sessionStorage)).not.toContain(PAT);
    expect(storageDump(localStorage)).not.toContain(PAT);
  });

  it("drops a restored PAT when the page is shown from the back-forward cache", async () => {
    useSessionStore.setState({
      user: sessionUser("user-a", "ada", "Ada"),
      permissionsReady: true,
    });
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) => {
        if (String(url).endsWith("/auth/me")) {
          return jsonResponse(200, meBody("user-a", "other-account", "Pat Owner"));
        }
        return jsonResponse(200, { tools: [] });
      }),
    );

    const { default: Layout } = await import("@/app/console/mcp/layout");
    const { McpMetadataDetail } = await import("@/features/mcp/McpMetadataDetail");
    render(shell(createElement(Layout, null, createElement(McpMetadataDetail))));

    fireEvent.change(screen.getByLabelText("Personal access token"), { target: { value: PAT } });
    act(() => {
      window.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: false }));
    });
    expect((screen.getByLabelText("Personal access token") as HTMLInputElement).value).toBe(PAT);

    fireEvent.click(screen.getByRole("button", { name: "Verify personal access token" }));
    expect(
      await screen.findByText("This personal access token belongs to the signed-in user. user-a"),
    ).toBeTruthy();

    act(() => {
      window.dispatchEvent(new PageTransitionEvent("pageshow", { persisted: true }));
    });
    expect((screen.getByLabelText("Personal access token") as HTMLInputElement).value).toBe("");
    expect(screen.queryByText(/belongs to the signed-in user/)).toBeNull();
    expect(screen.queryByText("user-a")).toBeNull();
    expect(screen.queryByText("Selected endpoint /mcp")).toBeNull();
    expect(document.body.textContent).not.toContain(PAT);
  });
});
