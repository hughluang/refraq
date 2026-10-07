/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AccessGrantsSection } from "@/features/entities/AccessGrantsSection";
import type { AccessSummary } from "@/features/entities/accessTypes";

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string) => key,
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

const summary: AccessSummary = {
  entity_id: "ent_1",
  head_version_id: "ver_1",
  policy_revision: 1,
  views: {
    state: "ready",
    revision: 1,
    single_profile_views: 1,
    combinations: 0,
    combination_limit: 10,
    subjects_over_limit: 0,
    latest_job_id: null,
  },
  ladders: [
    {
      attribute_id: "att_region",
      attribute_name: "region",
      type: "string",
      levels: [{ key: "clear", mode: "clear" }],
    },
  ],
  profiles: [],
  grants: [],
  restrictions: [],
};

function renderSection() {
  return render(
    createElement(
      MantineProvider,
      { env: "test" },
      createElement(AccessGrantsSection, {
        entityId: "ent_1",
        summary,
        users: [],
        roles: [],
        groups: [],
        subjectAttrs: [{ value: "regions", label: "Regions" }],
        busyId: null,
        run: vi.fn(async () => true),
        focusId: "grants",
        focusNonce: 0,
      }),
    ),
  );
}

function openList(name: string, optionName: string) {
  const combobox = screen.getByRole("combobox", { name, hidden: true });
  fireEvent.mouseDown(combobox);
  const lists = screen.getAllByRole("listbox", { hidden: true });
  const list = lists.find((item) =>
    within(item).queryByRole("option", { name: optionName, hidden: true }),
  );
  if (!list) throw new Error(`no listbox for ${name}`);
  return within(list);
}

describe("AccessGrantsSection row rule", () => {
  beforeEach(() => {
    stubDomApis();
  });

  afterEach(() => {
    cleanup();
  });

  it("hides a person's attribute until the comparison is is-one-of", () => {
    renderSection();
    fireEvent.click(screen.getByRole("button", { name: "entities.access.grants.add" }));
    fireEvent.click(
      screen.getByRole("button", { name: "entities.access.grants.limitRows", hidden: true }),
    );

    expect(screen.getByText("entities.access.rule.hint.subjectAttr", { hidden: true })).toBeTruthy();
    const hidden = openList("entities.access.rule.operand", "entities.access.rule.value");
    expect(
      hidden.queryByRole("option", { name: "entities.access.rule.subjectAttr", hidden: true }),
    ).toBeNull();
    expect(
      hidden.getByRole("option", { name: "entities.access.rule.value", hidden: true }),
    ).toBeTruthy();

    const comparisons = openList("entities.access.rule.op", "entities.access.rule.op.eq");
    fireEvent.click(
      comparisons.getByRole("option", { name: "entities.access.rule.op.in", hidden: true }),
    );

    expect(screen.queryByText("entities.access.rule.hint.subjectAttr", { hidden: true })).toBeNull();
    const shown = openList("entities.access.rule.operand", "entities.access.rule.value");
    expect(
      shown.getByRole("option", { name: "entities.access.rule.subjectAttr", hidden: true }),
    ).toBeTruthy();
  });
});
