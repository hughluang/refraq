/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AccessPolicySummary } from "@/features/entities/AccessPolicySummary";
import type { AccessSummary } from "@/features/entities/accessTypes";
import en from "@/locales/en-US/common.json";

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string, options?: Record<string, unknown>) => {
    const template = (en as Record<string, string>)[key] ?? key;
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
  class ResizeObserverStub {
    observe() {}
    unobserve() {}
    disconnect() {}
  }
  globalThis.ResizeObserver = ResizeObserverStub;
}

function summary(views: Partial<AccessSummary["views"]>, head: string | null = "ver_1"): AccessSummary {
  return {
    entity_id: "ent_1",
    head_version_id: head,
    policy_revision: 1,
    views: {
      state: "ready",
      revision: 1,
      single_profile_views: 1,
      combinations: 0,
      combination_limit: 64,
      subjects_over_limit: 0,
      latest_job_id: null,
      ...views,
    },
    ladders: [],
    profiles: [],
    grants: [],
    restrictions: [],
  };
}

function renderSummary(value: AccessSummary) {
  return render(
    createElement(
      MantineProvider,
      { env: "test" },
      createElement(AccessPolicySummary, { summary: value }),
    ),
  );
}

function badgeFor(label: string): HTMLElement {
  const labels = screen.getAllByText(label);
  const node =
    labels.find((item) => item.classList.contains("mantine-Badge-label")) ?? labels[0];
  if (!node) throw new Error(`missing badge for ${label}`);
  let current: HTMLElement | null = node;
  while (current) {
    if ((current.getAttribute("style") ?? "").includes("--badge-")) return current;
    current = current.parentElement;
  }
  throw new Error(`missing badge for ${label}`);
}

function badgePaint(label: string): string {
  return badgeFor(label).getAttribute("style") ?? "";
}

describe("AccessPolicySummary", () => {
  beforeEach(() => {
    stubDomApis();
  });

  afterEach(() => {
    cleanup();
  });

  it("shows a pending apply as a status badge whose tooltip is the pending sentence", () => {
    const sentence = en["entities.access.views.pending"];
    renderSummary(summary({ state: "pending" }));

    fireEvent.mouseEnter(badgeFor(sentence));
    expect(screen.getByRole("tooltip").textContent).toBe(sentence);
    expect(badgePaint(sentence)).toContain("yellow");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows a failed apply as a danger badge with the failed sentence", () => {
    const sentence = en["entities.access.views.failed"];
    renderSummary(summary({ state: "failed" }));

    fireEvent.mouseEnter(badgeFor(sentence));
    expect(screen.getByRole("tooltip").textContent).toBe(sentence);
    expect(badgePaint(sentence)).toContain("red");
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows a missing serving version as a warning badge with the no-head sentence", () => {
    const sentence = en["entities.access.views.noHead"];
    renderSummary(summary({ state: "ready" }, null));

    fireEvent.mouseEnter(badgeFor(sentence));
    expect(screen.getByRole("tooltip").textContent).toBe(sentence);
    expect(badgePaint(sentence)).toContain("yellow");
    expect(screen.queryByText(en["entities.access.views.ready"])).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("hides the view badge once the policy is applied", () => {
    renderSummary(summary({ state: "ready", combinations: 10, combination_limit: 64 }));

    expect(screen.queryByText(en["entities.access.views.ready"])).toBeNull();
    expect(screen.queryByText("Access schemes 10 / 64")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("shows a near-limit budget as n / limit in a warning badge", () => {
    renderSummary(summary({ state: "ready", combinations: 52, combination_limit: 64 }));

    const label = "Access schemes 52 / 64";
    expect(badgePaint(label)).toContain("yellow");
    expect(screen.queryByText(en["entities.access.overLimit"])).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("moves the over-limit sentence into the budget badge tooltip", () => {
    renderSummary(summary({ state: "ready", combinations: 65, combination_limit: 64 }));

    const label = "Access schemes 65 / 64";
    const explanation = en["entities.access.overLimit"];
    expect(badgePaint(label)).toContain("red");
    expect(screen.queryByText(explanation)).toBeNull();
    fireEvent.mouseEnter(badgeFor(label));
    expect(screen.getByRole("tooltip").textContent).toBe(explanation);
    expect(screen.getAllByText(explanation)).toHaveLength(1);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("treats a subject over its own cap as over the budget", () => {
    renderSummary(
      summary({ state: "ready", combinations: 1, combination_limit: 64, subjects_over_limit: 1 }),
    );

    const label = "Access schemes 1 / 64";
    const explanation = en["entities.access.overLimit"];
    expect(badgePaint(label)).toContain("red");
    fireEvent.mouseEnter(badgeFor(label));
    expect(screen.getByRole("tooltip").textContent).toBe(explanation);
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
