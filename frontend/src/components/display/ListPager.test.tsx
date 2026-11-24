/** @vitest-environment jsdom */
import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeAll, expect, it, vi } from "vitest";

import en from "@/locales/en-US/common.json";
import zh from "@/locales/zh-CN/common.json";

import { ListPager } from "./ListPager";

const locale = vi.hoisted(() => ({ value: "en-US" }));
vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) => {
    const dictionary = locale.value === "en-US" ? en : zh;
    return dictionary[key as keyof typeof dictionary] ?? key;
  },
}));

beforeAll(() => {
  window.matchMedia = vi.fn().mockImplementation((query: string) => ({
    matches: false,
    media: query,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
    addListener: vi.fn(),
    removeListener: vi.fn(),
  }));
});
afterEach(cleanup);

it.each([
  ["en-US", en],
  ["zh-CN", zh],
] as const)("names pagination controls in %s and preserves navigation", (language, dictionary) => {
  locale.value = language;
  const onChange = vi.fn();
  render(
    <MantineProvider>
      <ListPager page={2} pageSize={10} total={30} onChange={onChange} />
    </MantineProvider>,
  );

  fireEvent.click(screen.getByRole("button", { name: dictionary["common.prev"] }));
  expect(onChange).toHaveBeenLastCalledWith(1);
  fireEvent.click(screen.getByRole("button", { name: dictionary["common.next"] }));
  expect(onChange).toHaveBeenLastCalledWith(3);
});
