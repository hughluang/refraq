/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, render, screen } from "@testing-library/react";
import { createElement, type ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import zh from "@/locales/zh-CN/common.json";
import type { HttpAccount } from "@/features/http-accounts/types";

const getHttpAccount = vi.hoisted(() => vi.fn());

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) => (zh as Record<string, string>)[key] ?? key,
  useCan: () => ({ data: { can: true } }),
  useNotification: () => ({ open: vi.fn() }),
}));

vi.mock("@/features/http-accounts/api", () => ({
  getHttpAccount,
  createHttpAccount: vi.fn(),
  patchHttpAccount: vi.fn(),
  deleteHttpAccount: vi.fn(),
}));

vi.mock("@/components/navigation/useConsoleNavigation", () => ({
  useConsoleNavigation: () => ({ replace: vi.fn() }),
}));

vi.mock("@/components/layout/PageChrome", () => ({
  PageChrome: ({ children }: { children?: ReactNode }) => children,
}));

vi.mock("@/components/navigation/ConsoleLink", () => ({
  ConsoleLink: ({ children }: { children?: ReactNode }) => children,
}));

const ACCOUNT: HttpAccount = {
  id: "hac_bb2e851a5eb1",
  name: "Office",
  auth: { type: "bearer" },
  headers: [],
  query: [],
  allowed_origins: [],
  created_at: "2026-10-29T00:00:00Z",
  updated_at: "2026-10-29T00:00:00Z",
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
}

describe("HttpAccountRecord show", () => {
  afterEach(() => {
    cleanup();
    getHttpAccount.mockReset();
  });

  it("names an empty header list and an empty query list from the catalog", async () => {
    stubDomApis();
    getHttpAccount.mockResolvedValue({ http_account: ACCOUNT });
    const { HttpAccountRecord } = await import("@/features/http-accounts/HttpAccountRecord");
    render(
      createElement(
        MantineProvider,
        { env: "test" },
        createElement(HttpAccountRecord, { mode: "show", accountId: ACCOUNT.id }),
      ),
    );
    const sentence = zh["httpAccounts.fields.noneListed"];
    expect(sentence).toBeTruthy();
    expect(sentence).not.toBe("httpAccounts.fields.noneListed");
    expect(await screen.findAllByText(sentence)).toHaveLength(2);
    expect(screen.queryByText("httpAccounts.fields.noneListed")).toBeNull();
    expect(screen.getByText(zh["httpAccounts.fields.tokenSet"])).toBeTruthy();
  });
});
