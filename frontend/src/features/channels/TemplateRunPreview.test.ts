/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { act, cleanup, render, screen } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  bindTemplatePreview,
  PREVIEW_PAUSE_MS,
  TemplateRunPreview,
  type TemplatePreviewSource,
} from "@/features/channels/TemplateRunPreview";
import type { TemplatePreviewResult } from "@/features/channels/types";
import { ApiError } from "@/lib/api";

const LABELS: Record<string, string> = {
  "channels.template.preview.title": "Preview",
  "channels.template.preview.noRun": "No run yet",
  "channels.template.preview.pending": "Calculating",
  "channels.template.preview.failed": "Calculation failed",
  "channels.template.preview.missingNodes": "No output from {{nodes}}",
  "channels.template.preview.missingContext": "No run context",
  "channels.template.preview.truncated": "Only the beginning",
  "channels.template.preview.empty": "Empty string",
  "channels.template.preview.unavailable": "Unavailable",
  "problems.CHANNEL_VALUE_TYPE_MISMATCH": "Type mismatch",
  "problems.REQUEST_INVALID": "Request invalid",
};

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string, values?: Record<string, unknown>) => {
    const template = LABELS[key] ?? key;
    if (!values) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(values[name] ?? ""));
  },
}));

const NAMES: Record<string, string> = { nd_keep: "Keep lease", nd_read: "Read back" };

type Evaluate = () => Promise<TemplatePreviewResult>;

function source(evaluate: Evaluate, key = "run-1"): TemplatePreviewSource {
  return { target: "field", run: { key, evaluate }, nodeName: (id) => NAMES[id] ?? id };
}

function ok(value: unknown, truncated = false): TemplatePreviewResult {
  return { state: "ok", value, truncated };
}

function preview(from: TemplatePreviewSource, text = "{{ 1 }}", raw = false) {
  return createElement(
    MantineProvider,
    { env: "test" },
    createElement(TemplateRunPreview, { source: from, text, scopeKey: "[]", raw }),
  );
}

async function elapse(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

function shownValue(): string | null | undefined {
  return document.querySelector(".channel-template-field__value")?.textContent;
}

function busy(): string | null | undefined {
  return document.querySelector(".channel-template-field__preview")?.getAttribute("aria-busy");
}

beforeEach(() => {
  vi.useFakeTimers();
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    }),
  });
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("template run preview", () => {
  it("asks for a run while the channel has none", () => {
    render(preview({ target: "field", run: null, nodeName: (id) => id }));
    expect(screen.getByText("No run yet")).toBeTruthy();
    expect(busy()).toBe("false");
  });

  it("shows a string as its text and any other value as JSON", async () => {
    const view = render(preview(source(async () => ok("lease-3")), "lease-{{ 3 }}", true));
    await elapse();
    expect(shownValue()).toBe("lease-3");
    view.unmount();

    render(preview(source(async () => ok({ count: 6 }, true))));
    await elapse();
    expect(shownValue()).toBe('{\n  "count": 6\n}');
    expect(screen.getByText("Only the beginning")).toBeTruthy();
  });

  it("marks an empty string instead of showing nothing", async () => {
    render(preview(source(async () => ok("")), "{{ '' }}", true));
    await elapse();
    expect(screen.getByText("Empty string")).toBeTruthy();
    expect(shownValue()).toBeUndefined();
  });

  it("explains why the template did not evaluate", async () => {
    const view = render(
      preview(
        source(async () => ({
          state: "failed",
          code: "CHANNEL_NODE_FAILED",
          message: "NameError: name 'absent' is not defined",
        })),
      ),
    );
    await elapse();
    expect(screen.getByText("Calculation failed")).toBeTruthy();
    expect(screen.getByText("NameError: name 'absent' is not defined")).toBeTruthy();
    view.unmount();

    render(
      preview(
        source(async () => ({
          state: "failed",
          code: "CHANNEL_VALUE_TYPE_MISMATCH",
          message: "Value does not match the declared type",
        })),
      ),
    );
    await elapse();
    expect(screen.getByText("Type mismatch")).toBeTruthy();
  });

  it("names the nodes the run has not reached and a missing run context", async () => {
    render(
      preview(source(async () => ({ state: "missing", node_ids: ["nd_keep", "nd_read"], context: true }))),
    );
    await elapse();
    expect(screen.getByText("No output from Keep lease, Read back")).toBeTruthy();
    expect(screen.getByText("No run context")).toBeTruthy();
  });

  it("reports a refused request", async () => {
    render(
      preview(source(() => Promise.reject(new ApiError(422, "REQUEST_INVALID", "path is not a template")))),
    );
    await elapse();
    expect(screen.getByText("Request invalid")).toBeTruthy();
  });

  it("waits for a pause after an edit and keeps the last value meanwhile", async () => {
    const evaluate = vi.fn<Evaluate>().mockResolvedValueOnce(ok(1)).mockResolvedValueOnce(ok(2));
    const from = source(evaluate);
    const view = render(preview(from, "{{ 1 }}"));
    await elapse();
    expect(shownValue()).toBe("1");
    expect(busy()).toBe("false");

    view.rerender(preview(from, "{{ 2 }}"));
    expect(shownValue()).toBe("1");
    expect(busy()).toBe("true");
    await elapse(PREVIEW_PAUSE_MS - 1);
    expect(evaluate).toHaveBeenCalledTimes(1);
    await elapse(1);
    expect(evaluate).toHaveBeenCalledTimes(2);
    expect(shownValue()).toBe("2");
    expect(busy()).toBe("false");
  });

  it("evaluates again when the run records more", async () => {
    const evaluate = vi.fn<Evaluate>().mockResolvedValueOnce(ok("first")).mockResolvedValueOnce(ok("second"));
    const view = render(preview(source(evaluate, "run-1|running"), "{{ 1 }}", true));
    await elapse();
    view.rerender(preview(source(evaluate, "run-1|succeeded"), "{{ 1 }}", true));
    await elapse(PREVIEW_PAUSE_MS);
    expect(evaluate).toHaveBeenCalledTimes(2);
    expect(shownValue()).toBe("second");
  });

  it("ignores an answer that arrives after a newer edit", async () => {
    let answerFirst: (result: TemplatePreviewResult) => void = () => {};
    const evaluate = vi
      .fn<Evaluate>()
      .mockImplementationOnce(
        () =>
          new Promise((resolve) => {
            answerFirst = resolve;
          }),
      )
      .mockResolvedValueOnce(ok("new"));
    const from = source(evaluate);
    const view = render(preview(from, "{{ 'old' }}", true));
    await elapse();
    view.rerender(preview(from, "{{ 'new' }}", true));
    await elapse(PREVIEW_PAUSE_MS);
    expect(shownValue()).toBe("new");

    await act(async () => {
      answerFirst(ok("old"));
    });
    expect(shownValue()).toBe("new");
  });

  it("binds a field to its node and configuration path", async () => {
    const evaluate = vi.fn().mockResolvedValue(ok(6));
    const bound = bindTemplatePreview({ run: { key: "run-1", evaluate } }, "nd_keep", ["value"], (id) => id);
    expect(bound.run?.key).toBe("run-1");
    await bound.run?.evaluate();
    expect(evaluate).toHaveBeenCalledWith("nd_keep", ["value"]);
    expect(bindTemplatePreview({ run: null }, "nd_keep", ["value"], (id) => id).run).toBeNull();
  });
});
