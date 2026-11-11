/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { InboundCredential } from "@/features/inbound-credentials/types";

const getInboundCredential = vi.hoisted(() => vi.fn());
const createInboundCredential = vi.hoisted(() => vi.fn());
const patchInboundCredential = vi.hoisted(() => vi.fn());
const deleteInboundCredential = vi.hoisted(() => vi.fn());
const replace = vi.hoisted(() => vi.fn());
const notify = vi.hoisted(() => vi.fn());
const locationReplace = vi.hoisted(() => vi.fn());
const locationAssign = vi.hoisted(() => vi.fn());
const access = vi.hoisted(() => ({ can: true as boolean | undefined }));

vi.mock("@refinedev/core", () => ({
  matchResourceFromRoute: () => ({ found: false }),
  useTranslate: () => (key: string) => key,
  useCan: () => ({
    data: access.can === undefined ? undefined : { can: access.can },
  }),
  useNotification: () => ({ open: notify }),
  useBreadcrumb: () => ({ breadcrumbs: [] }),
}));

vi.mock("@/features/inbound-credentials/api", () => ({
  getInboundCredential,
  createInboundCredential,
  patchInboundCredential,
  deleteInboundCredential,
}));

vi.mock("@/components/navigation/useConsoleNavigation", () => ({
  useConsoleNavigation: () => ({
    replace,
    push: vi.fn(),
    refresh: vi.fn(),
    pending: false,
  }),
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

const HMAC: InboundCredential = {
  id: "icr_abcdefabcdef",
  name: "Signed hook",
  type: "hmac_sha256",
  config: {
    signature_header: "X-Signature",
    encoding: "hex",
    prefix: "sha256=",
    timestamp_header: "X-Timestamp",
  },
  created_at: "2026-10-01T02:00:00Z",
  updated_at: "2026-10-20T02:00:00Z",
};

const STORED_SECRET = "stored-secret-value";

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

function chooseOption(label: string, optionName: string) {
  const combobox = screen.getByRole("combobox", { name: label });
  fireEvent.mouseDown(combobox);
  const lists = screen.getAllByRole("listbox", { hidden: true });
  const list = lists.find((item) =>
    within(item).queryByRole("option", { name: optionName, hidden: true }),
  );
  if (!list) throw new Error(`no listbox for ${optionName}`);
  fireEvent.click(within(list).getByRole("option", { name: optionName, hidden: true }));
}

async function renderRecord(
  props: { mode: "create" } | { mode: "show" | "edit"; credentialId: string },
) {
  const { InboundCredentialRecord } = await import(
    "@/features/inbound-credentials/InboundCredentialRecord"
  );
  render(shell(createElement(InboundCredentialRecord, props)));
}

describe("InboundCredentialRecord", () => {
  beforeEach(() => {
    stubDomApis();
    access.can = true;
    getInboundCredential.mockReset();
    createInboundCredential.mockReset();
    patchInboundCredential.mockReset();
    deleteInboundCredential.mockReset();
    replace.mockReset();
    notify.mockReset();
    locationReplace.mockReset();
    locationAssign.mockReset();
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { replace: locationReplace, assign: locationAssign },
    });
  });

  afterEach(async () => {
    cleanup();
    const guard = await import("@/components/navigation/leaveGuard");
    if (guard.leavePromptOpen()) guard.settleLeavePrompt(false);
    guard.releaseLeaveGuardSuppression();
    vi.restoreAllMocks();
  });

  it("shows the token fields returned by the API and never the secret", async () => {
    getInboundCredential.mockResolvedValue({
      inbound_credential: { ...TOKEN, secret: STORED_SECRET },
    });
    await renderRecord({ mode: "show", credentialId: TOKEN.id });

    expect(await screen.findByRole("heading", { name: TOKEN.name })).toBeTruthy();
    expect(document.querySelectorAll("[data-page-header]")).toHaveLength(1);
    expect(screen.getByText("inboundCredentials.types.token")).toBeTruthy();
    expect(screen.getByText("inboundCredentials.location.header")).toBeTruthy();
    expect(screen.getByText("X-Hook-Token")).toBeTruthy();
    expect(screen.getByText("inboundCredentials.fields.secretSet")).toBeTruthy();
    expect(screen.queryByText(STORED_SECRET)).toBeNull();
    expect(screen.queryByLabelText("inboundCredentials.fields.secret")).toBeNull();
    expect(document.querySelector("input[type='password']")).toBeNull();
    expect(screen.queryByText("inboundCredentials.fields.signatureHeader")).toBeNull();
    expect(screen.queryByText("X-Signature")).toBeNull();
    expect(
      screen.getByRole("link", { name: "inboundCredentials.backToList" }).getAttribute("href"),
    ).toBe("/console/inbound-credentials");
    expect(screen.getByRole("button", { name: "jobs.refresh" })).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "actions.edit" }).getAttribute("href"),
    ).toBe(`/console/inbound-credentials/${TOKEN.id}/edit`);
    expect(screen.queryByRole("link", { name: "common.cancel" })).toBeNull();
    expect(screen.getByRole("button", { name: "actions.delete" })).toBeTruthy();
  });

  it("shows the HMAC fields returned by the API", async () => {
    getInboundCredential.mockResolvedValue({ inbound_credential: HMAC });
    await renderRecord({ mode: "show", credentialId: HMAC.id });

    expect(await screen.findByRole("heading", { name: HMAC.name })).toBeTruthy();
    expect(screen.getByText("inboundCredentials.types.hmac_sha256")).toBeTruthy();
    expect(screen.getByText("X-Signature")).toBeTruthy();
    expect(screen.getByText("inboundCredentials.encoding.hex")).toBeTruthy();
    expect(screen.getByText("sha256=")).toBeTruthy();
    expect(screen.getByText("X-Timestamp")).toBeTruthy();
    expect(screen.getByText("inboundCredentials.fields.secretSet")).toBeTruthy();
    expect(screen.queryByText("inboundCredentials.location.header")).toBeNull();
    expect(screen.queryByText("inboundCredentials.location.query")).toBeNull();
    expect(screen.queryByLabelText("inboundCredentials.fields.parameterName")).toBeNull();
    expect(document.querySelector("input[type='password']")).toBeNull();
  });

  it("leaves the edit URL when the caller cannot write", async () => {
    access.can = false;
    getInboundCredential.mockResolvedValue({ inbound_credential: TOKEN });
    await renderRecord({ mode: "edit", credentialId: TOKEN.id });

    await waitFor(() => {
      expect(replace).toHaveBeenCalledWith(`/console/inbound-credentials/${TOKEN.id}`);
    });
  });

  it("keeps a reader on show and hides write actions", async () => {
    access.can = false;
    getInboundCredential.mockResolvedValue({ inbound_credential: TOKEN });
    await renderRecord({ mode: "show", credentialId: TOKEN.id });

    expect(await screen.findByRole("heading", { name: TOKEN.name })).toBeTruthy();
    expect(screen.queryByRole("link", { name: "actions.edit" })).toBeNull();
    expect(screen.queryByRole("button", { name: "actions.delete" })).toBeNull();
    expect(replace).not.toHaveBeenCalled();
  });

  it("omits an empty secret on edit and stays on edit", async () => {
    getInboundCredential.mockResolvedValue({
      inbound_credential: { ...TOKEN, secret: STORED_SECRET },
    });
    patchInboundCredential.mockImplementation(async (_id: string, body: { name?: string }) => ({
      inbound_credential: { ...TOKEN, name: body.name ?? TOKEN.name },
    }));
    await renderRecord({ mode: "edit", credentialId: TOKEN.id });

    expect(await screen.findByDisplayValue(TOKEN.name)).toBeTruthy();
    fireEvent.click(
      screen.getByRole("button", {
        name: "inboundCredentials.fields.secret form.field.description",
      }),
    );
    expect(screen.getByText("inboundCredentials.fields.secretKeep")).toBeTruthy();
    expect((screen.getByLabelText("inboundCredentials.fields.secret") as HTMLInputElement).value).toBe(
      "",
    );
    fireEvent.change(screen.getByLabelText("inboundCredentials.fields.name"), {
      target: { value: "Renamed hook" },
    });
    fireEvent.submit(document.getElementById("inbound-credential-record-form") as HTMLFormElement);

    await waitFor(() => {
      expect(patchInboundCredential).toHaveBeenCalledWith(TOKEN.id, { name: "Renamed hook" });
    });
    expect(patchInboundCredential.mock.calls[0]?.[1]).not.toHaveProperty("secret");
    expect(locationReplace).not.toHaveBeenCalled();
    expect(replace).not.toHaveBeenCalled();
    expect(await screen.findByDisplayValue("Renamed hook")).toBeTruthy();
    expect(
      screen.getByRole("link", { name: "common.cancel" }).getAttribute("href"),
    ).toBe(`/console/inbound-credentials/${TOKEN.id}`);
    expect(
      screen.getByRole("link", { name: "inboundCredentials.backToList" }).getAttribute("href"),
    ).toBe("/console/inbound-credentials");
  });

  it("sends a secret only when the operator typed one", async () => {
    getInboundCredential.mockResolvedValue({ inbound_credential: TOKEN });
    patchInboundCredential.mockResolvedValue({ inbound_credential: TOKEN });
    await renderRecord({ mode: "edit", credentialId: TOKEN.id });
    expect(await screen.findByDisplayValue(TOKEN.name)).toBeTruthy();

    fireEvent.change(screen.getByLabelText("inboundCredentials.fields.secret"), {
      target: { value: "next-secret" },
    });
    fireEvent.submit(document.getElementById("inbound-credential-record-form") as HTMLFormElement);

    await waitFor(() => {
      expect(patchInboundCredential).toHaveBeenCalledWith(TOKEN.id, { secret: "next-secret" });
    });
    expect(
      (screen.getByLabelText("inboundCredentials.fields.secret") as HTMLInputElement).value,
    ).toBe("");
  });

  it("sends the HMAC config when the operator switches type and leaves the secret blank", async () => {
    getInboundCredential.mockResolvedValue({ inbound_credential: TOKEN });
    patchInboundCredential.mockResolvedValue({
      inbound_credential: {
        ...HMAC,
        id: TOKEN.id,
        name: TOKEN.name,
      },
    });
    await renderRecord({ mode: "edit", credentialId: TOKEN.id });
    expect(await screen.findByDisplayValue("X-Hook-Token")).toBeTruthy();

    chooseOption("inboundCredentials.fields.type", "inboundCredentials.types.hmac_sha256");
    expect(screen.queryByLabelText("inboundCredentials.fields.parameterName")).toBeNull();
    fireEvent.change(screen.getByLabelText("inboundCredentials.fields.signatureHeader"), {
      target: { value: "X-Signature" },
    });
    fireEvent.change(screen.getByLabelText("inboundCredentials.fields.prefix"), {
      target: { value: "sha256=" },
    });
    fireEvent.submit(document.getElementById("inbound-credential-record-form") as HTMLFormElement);

    await waitFor(() => {
      expect(patchInboundCredential).toHaveBeenCalledWith(TOKEN.id, {
        type: "hmac_sha256",
        config: {
          signature_header: "X-Signature",
          encoding: "hex",
          prefix: "sha256=",
        },
      });
    });
    expect(patchInboundCredential.mock.calls[0]?.[1]).not.toHaveProperty("secret");
  });

  it("creates a token credential and opens its edit route", async () => {
    createInboundCredential.mockResolvedValue({ inbound_credential: TOKEN });
    await renderRecord({ mode: "create" });

    expect(screen.getByRole("heading", { name: "inboundCredentials.createTitle" })).toBeTruthy();
    expect(document.querySelectorAll("[data-page-header]")).toHaveLength(1);
    expect(screen.queryByRole("link", { name: "inboundCredentials.backToList" })).toBeNull();
    expect(screen.queryByRole("button", { name: "jobs.refresh" })).toBeNull();
    expect(screen.getByRole("link", { name: "common.cancel" }).getAttribute("href")).toBe(
      "/console/inbound-credentials",
    );
    fireEvent.click(
      screen.getByRole("button", {
        name: "inboundCredentials.fields.secret form.field.description",
      }),
    );
    expect(screen.getByText("inboundCredentials.fields.secretHint")).toBeTruthy();
    expect(screen.getByLabelText("inboundCredentials.fields.parameterName")).toBeTruthy();
    expect(screen.queryByLabelText("inboundCredentials.fields.signatureHeader")).toBeNull();

    fireEvent.change(screen.getByLabelText("inboundCredentials.fields.name"), {
      target: { value: "Partner hook" },
    });
    fireEvent.change(screen.getByLabelText("inboundCredentials.fields.parameterName"), {
      target: { value: "X-Hook-Token" },
    });
    fireEvent.change(screen.getByLabelText("inboundCredentials.fields.secret"), {
      target: { value: "secret" },
    });
    fireEvent.submit(document.getElementById("inbound-credential-record-form") as HTMLFormElement);

    await waitFor(() => {
      expect(createInboundCredential).toHaveBeenCalledWith({
        name: "Partner hook",
        type: "token",
        secret: "secret",
        config: { location: "header", name: "X-Hook-Token" },
      });
    });
    expect(locationReplace).toHaveBeenCalledWith(
      `/console/inbound-credentials/${TOKEN.id}/edit`,
    );
  });

  it("creates an HMAC credential from the fields that type accepts", async () => {
    createInboundCredential.mockResolvedValue({ inbound_credential: HMAC });
    await renderRecord({ mode: "create" });

    chooseOption("inboundCredentials.fields.type", "inboundCredentials.types.hmac_sha256");
    expect(screen.queryByLabelText("inboundCredentials.fields.parameterName")).toBeNull();
    fireEvent.change(screen.getByLabelText("inboundCredentials.fields.name"), {
      target: { value: "Signed hook" },
    });
    fireEvent.change(screen.getByLabelText("inboundCredentials.fields.signatureHeader"), {
      target: { value: "X-Signature" },
    });
    chooseOption("inboundCredentials.fields.encoding", "inboundCredentials.encoding.base64");
    fireEvent.change(screen.getByLabelText("inboundCredentials.fields.timestampHeader"), {
      target: { value: "X-Timestamp" },
    });
    fireEvent.change(screen.getByLabelText("inboundCredentials.fields.secret"), {
      target: { value: "secret" },
    });
    fireEvent.submit(document.getElementById("inbound-credential-record-form") as HTMLFormElement);

    await waitFor(() => {
      expect(createInboundCredential).toHaveBeenCalledWith({
        name: "Signed hook",
        type: "hmac_sha256",
        secret: "secret",
        config: {
          signature_header: "X-Signature",
          encoding: "base64",
          timestamp_header: "X-Timestamp",
        },
      });
    });
    const body = createInboundCredential.mock.calls[0]?.[0] as { config: Record<string, string> };
    expect(body.config).not.toHaveProperty("prefix");
    expect(locationReplace).toHaveBeenCalledWith(
      `/console/inbound-credentials/${HMAC.id}/edit`,
    );
  });

  it("reloads the record from refresh and deletes only after confirmation", async () => {
    getInboundCredential.mockResolvedValue({ inbound_credential: TOKEN });
    deleteInboundCredential.mockResolvedValue(undefined);
    await renderRecord({ mode: "show", credentialId: TOKEN.id });
    expect(await screen.findByRole("heading", { name: TOKEN.name })).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "jobs.refresh" }));
    await waitFor(() => expect(getInboundCredential).toHaveBeenCalledTimes(2));

    fireEvent.click(screen.getByRole("button", { name: "actions.delete" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("inboundCredentials.deleteTitle")).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "actions.delete" }));

    await waitFor(() => expect(deleteInboundCredential).toHaveBeenCalledWith(TOKEN.id));
    expect(locationAssign).toHaveBeenCalledWith("/console/inbound-credentials");
  });
});
