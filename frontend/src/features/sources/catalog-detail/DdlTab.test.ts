/** @vitest-environment jsdom */
import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import en from "@/locales/en-US/common.json";
import { DdlTab, tokenizeSqlLines } from "./DdlTab";

const clipboard = vi.hoisted(() => ({ copyText: vi.fn() }));
const notice = vi.hoisted(() => vi.fn());

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string, options?: Record<string, unknown>) =>
    ((en as Record<string, string>)[key] ?? key).replace(
      /\{\{(\w+)\}\}/g,
      (_, name: string) => String(options?.[name] ?? ""),
    ),
  useNotification: () => ({ open: notice }),
}));

vi.mock("@/lib/copy-text", () => ({
  copyText: clipboard.copyText,
}));

function mount(props: { ddl: string | null; objectType?: string; objectName?: string }) {
  return render(
    createElement(MantineProvider, { env: "test" }, createElement(DdlTab, props)),
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  clipboard.copyText.mockResolvedValue(undefined);
  Object.defineProperty(window, "matchMedia", {
    value: (query: string) => ({
      matches: false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
    configurable: true,
  });
  Element.prototype.scrollIntoView = vi.fn();
});

afterEach(cleanup);

describe("DdlTab", () => {
  it("renders contextual empty state for tables and routines", () => {
    const { unmount } = mount({ ddl: null, objectType: "table" });
    expect(screen.getByText(en["catalog.ddl.emptyTable"])).toBeTruthy();
    unmount();

    mount({ ddl: null, objectType: "function" });
    expect(screen.getByText(en["catalog.ddl.emptyRoutine"])).toBeTruthy();
  });

  it("displays line and byte stats, line numbers, and SQL token highlighting", () => {
    const ddl = [
      "-- Orders table",
      "CREATE TABLE public.orders (",
      "  id BIGINT PRIMARY KEY,",
      "  status VARCHAR DEFAULT 'open',",
      "  amount NUMERIC DEFAULT 100",
      ");",
    ].join("\n");

    const { container } = mount({ ddl, objectType: "table", objectName: "public.orders" });

    expect(screen.getByText("public.orders")).toBeTruthy();
    expect(screen.getByText(/6 lines/)).toBeTruthy();

    // Line numbers 1..6 in non-selectable gutter
    const gutters = Array.from(container.querySelectorAll("span")).filter(
      (el) => el.style.userSelect === "none",
    );
    expect(gutters.map((el) => el.textContent)).toEqual(["1", "2", "3", "4", "5", "6"]);

    // Token highlighting uses Mantine CSS variables
    const tokens = tokenizeSqlLines(ddl);
    expect(tokens[0][0]).toEqual({ kind: "comment", text: "-- Orders table" });
    expect(tokens[1][0]).toEqual({ kind: "keyword", text: "CREATE" });
    expect(tokens[3].some((tok) => tok.kind === "string" && tok.text === "'open'")).toBe(true);
    expect(tokens[4].some((tok) => tok.kind === "number" && tok.text === "100")).toBe(true);
  });

  it("supports in-DDL search with match count and prev/next navigation", () => {
    const ddl = "CREATE TABLE t (\n  id INT,\n  parent_id INT\n);";
    const { container } = mount({ ddl });

    const searchInput = screen.getByRole("textbox", {
      name: en["catalog.ddl.searchPlaceholder"],
    });
    const prevBtn = screen.getByRole("button", { name: en["catalog.ddl.prevMatch"] });
    const nextBtn = screen.getByRole("button", { name: en["catalog.ddl.nextMatch"] });
    expect((prevBtn as HTMLButtonElement).disabled).toBe(true);
    expect((nextBtn as HTMLButtonElement).disabled).toBe(true);

    fireEvent.change(searchInput, { target: { value: "int" } });
    expect(screen.getByText("1 / 2")).toBeTruthy();
    expect((prevBtn as HTMLButtonElement).disabled).toBe(false);
    expect((nextBtn as HTMLButtonElement).disabled).toBe(false);

    let marks = container.querySelectorAll("mark");
    expect(marks).toHaveLength(2);
    expect(marks[0].getAttribute("data-active-match")).toBe("true");
    expect(marks[1].getAttribute("data-active-match")).toBeNull();

    fireEvent.click(nextBtn);
    expect(screen.getByText("2 / 2")).toBeTruthy();
    marks = container.querySelectorAll("mark");
    expect(marks[1].getAttribute("data-active-match")).toBe("true");

    fireEvent.click(prevBtn);
    expect(screen.getByText("1 / 2")).toBeTruthy();

    fireEvent.change(searchInput, { target: { value: "nonexistent" } });
    expect(screen.getByText(en["catalog.ddl.noMatches"])).toBeTruthy();
  });

  it("toggles wrap lines switch", () => {
    const ddl = "SELECT 1;";
    const { container } = mount({ ddl });
    const wrapSwitch = screen.getByRole("switch", { name: en["catalog.ddl.wrapLines"] });
    expect((wrapSwitch as HTMLInputElement).checked).toBe(false);

    const codeLines = Array.from(container.querySelectorAll("span")).filter(
      (el) => el.style.whiteSpace === "pre" || el.style.whiteSpace === "pre-wrap",
    );
    expect(codeLines[0].style.whiteSpace).toBe("pre");

    fireEvent.click(wrapSwitch);
    expect((wrapSwitch as HTMLInputElement).checked).toBe(true);
    expect(codeLines[0].style.whiteSpace).toBe("pre-wrap");
  });

  it("copies DDL and reports success or failure", async () => {
    const ddl = "SELECT 1;";
    mount({ ddl });
    const copyBtn = screen.getByRole("button", { name: en["catalog.ddl.copy"] });

    fireEvent.click(copyBtn);
    await waitFor(() => expect(clipboard.copyText).toHaveBeenCalledWith(ddl));
    expect(notice).toHaveBeenLastCalledWith({
      type: "success",
      message: en["common.copy.success"],
    });

    clipboard.copyText.mockRejectedValueOnce(new Error("denied"));
    fireEvent.click(copyBtn);
    await waitFor(() =>
      expect(notice).toHaveBeenLastCalledWith({
        type: "error",
        message: en["common.copy.failed"],
      }),
    );
  });
});
