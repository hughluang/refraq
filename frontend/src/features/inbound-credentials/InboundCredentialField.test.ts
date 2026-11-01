/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { InboundCredential } from "@/features/inbound-credentials/types";

const listInboundCredentials = vi.hoisted(() => vi.fn());
const getInboundCredential = vi.hoisted(() => vi.fn());

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) => key,
}));

vi.mock("@/features/inbound-credentials/api", () => ({
  listInboundCredentials,
  getInboundCredential,
}));

const TOKEN: InboundCredential = {
  id: "icr_0123456789ab",
  name: "Partner hook",
  type: "token",
  config: { location: "header", name: "X-Hook-Token" },
  created_at: "2026-10-01T02:00:00Z",
  updated_at: "2026-10-20T02:00:00Z",
};

const HMAC: InboundCredential = {
  id: "icr_abcdefabcdef",
  name: "Signed hook",
  type: "hmac_sha256",
  config: { signature_header: "X-Signature", encoding: "hex" },
  created_at: "2026-10-02T02:00:00Z",
  updated_at: "2026-10-02T02:00:00Z",
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

function shell(node: ReactNode) {
  return createElement(MantineProvider, { env: "test" }, node);
}

function page(items: InboundCredential[]) {
  return { items, total: items.length, limit: 200, offset: 0 };
}

describe("InboundCredentialField", () => {
  beforeEach(() => {
    stubDomApis();
    listInboundCredentials.mockReset();
    getInboundCredential.mockReset();
  });

  afterEach(() => {
    cleanup();
  });

  it("offers saved credentials by name and type and does not show a secret", async () => {
    listInboundCredentials.mockResolvedValue(
      page([
        { ...TOKEN, secret: "stored-secret-value" } as InboundCredential,
        HMAC,
      ]),
    );
    const onChange = vi.fn();
    const { InboundCredentialField } = await import(
      "@/features/inbound-credentials/InboundCredentialField"
    );
    render(
      shell(
        createElement(InboundCredentialField, {
          label: "Credential",
          value: "",
          editable: true,
          onChange,
        }),
      ),
    );

    const combobox = await screen.findByRole("combobox", { name: "Credential" });
    fireEvent.mouseDown(combobox);
    const option = await screen.findByRole("option", { name: /Partner hook/, hidden: true });
    expect(option.textContent).toContain("inboundCredentials.types.token");
    expect(
      screen.getByRole("option", { name: /Signed hook/, hidden: true }).textContent,
    ).toContain("inboundCredentials.types.hmac_sha256");
    expect(screen.queryByText("stored-secret-value")).toBeNull();
    expect(screen.queryByText("X-Hook-Token")).toBeNull();
    fireEvent.click(option);
    expect(onChange.mock.calls[0]?.[0]).toBe(TOKEN.id);
    expect(listInboundCredentials).toHaveBeenCalledWith({ limit: 200 });
  });

  it("names a credential the list page does not include", async () => {
    listInboundCredentials.mockResolvedValue(page([HMAC]));
    getInboundCredential.mockRejectedValue(new Error("missing"));
    const { InboundCredentialField } = await import(
      "@/features/inbound-credentials/InboundCredentialField"
    );
    render(
      shell(
        createElement(InboundCredentialField, {
          label: "Credential",
          value: TOKEN.id,
          editable: false,
          onChange: vi.fn(),
        }),
      ),
    );
    expect(await screen.findByText("inboundCredentials.picker.missing")).toBeTruthy();
    expect(getInboundCredential).toHaveBeenCalledWith(TOKEN.id);
  });

  it("reports a list load failure on the field", async () => {
    listInboundCredentials.mockRejectedValue(new Error("down"));
    const { InboundCredentialField } = await import(
      "@/features/inbound-credentials/InboundCredentialField"
    );
    render(
      shell(
        createElement(InboundCredentialField, {
          label: "Credential",
          value: "",
          editable: true,
          onChange: vi.fn(),
        }),
      ),
    );
    expect(await screen.findByText("inboundCredentials.picker.loadFailed")).toBeTruthy();
  });

  it("shows the credential name when the value is in the list", async () => {
    listInboundCredentials.mockResolvedValue(page([TOKEN]));
    const { InboundCredentialField } = await import(
      "@/features/inbound-credentials/InboundCredentialField"
    );
    render(
      shell(
        createElement(InboundCredentialField, {
          label: "Credential",
          value: TOKEN.id,
          editable: false,
          onChange: vi.fn(),
        }),
      ),
    );
    expect(await screen.findByText(TOKEN.name)).toBeTruthy();
    expect(screen.queryByText(TOKEN.id)).toBeNull();
    expect(within(document.body).queryByText("stored-secret-value")).toBeNull();
  });
});
