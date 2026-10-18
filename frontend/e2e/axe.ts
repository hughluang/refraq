import AxeBuilder from "@axe-core/playwright";
import { expect, type Page } from "@playwright/test";

export const AXE_TAGS = [
  "wcag2a",
  "wcag2aa",
  "wcag21a",
  "wcag21aa",
  "wcag22aa",
] as const;

export type AxeException = { id: string; reason: string };

export const AXE_EXCEPTIONS: readonly AxeException[] = [
  {
    id: "color-contrast",
    reason:
      "Filled Mantine buttons use the Site Branding primary (data-variant=filled, or the default filled style when the attribute is omitted). White on that shade is 3.55:1 at 14px. The suite does not retune a brand input. Any other color-contrast node fails the run.",
  },
];

type ContrastNode = { html: string; target: readonly unknown[] };

function filledButtonMarkup(html: string): boolean {
  return html.includes('data-variant="filled"') && html.includes("mantine-Button");
}

function firstSelector(target: readonly unknown[]): string | null {
  for (const item of target) {
    if (typeof item === "string") return item;
  }
  return null;
}

async function isBrandFilledButton(page: Page, node: ContrastNode): Promise<boolean> {
  if (filledButtonMarkup(node.html)) return true;
  const selector = firstSelector(node.target);
  if (!selector) return false;
  const host = page.locator(selector).first();
  if ((await host.count()) === 0) return false;
  return host.evaluate((element) => {
    const button = element.closest(".mantine-Button-root");
    if (!button) return false;
    const variant = button.getAttribute("data-variant");
    return variant === null || variant === "filled";
  });
}

export async function expectAccessible(page: Page) {
  const results = await new AxeBuilder({ page }).withTags([...AXE_TAGS]).analyze();
  const violations = [];
  for (const violation of results.violations) {
    if (violation.id !== "color-contrast") {
      violations.push(violation);
      continue;
    }
    const nodes = [];
    for (const node of violation.nodes) {
      if (!(await isBrandFilledButton(page, node))) nodes.push(node);
    }
    if (nodes.length > 0) violations.push({ ...violation, nodes });
  }
  expect(violations, JSON.stringify(violations, null, 2)).toEqual([]);
}
