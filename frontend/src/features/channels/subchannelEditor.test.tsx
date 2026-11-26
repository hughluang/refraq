/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { useState, type ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { listChannels, getVersion } from "@/features/channels/api";
import { CallChannelFields } from "@/features/channels/CallChannelFields";
import { SubchannelTriggerFields } from "@/features/channels/SubchannelTriggerFields";
import en from "@/locales/en-US/common.json";

const EN = en as Record<string, string>;

vi.mock("@refinedev/core", () => ({
  useTranslate: () => (key: string, options?: Record<string, unknown>) => {
    let text = EN[key] ?? (typeof options?.defaultValue === "string" ? options.defaultValue : key);
    if (options) {
      for (const [k, v] of Object.entries(options)) {
        if (k !== "defaultValue") text = text.replaceAll(`{{${k}}}`, String(v));
      }
    }
    return text;
  },
}));

vi.mock("@/features/channels/api", () => ({
  listChannels: vi.fn(),
  getVersion: vi.fn(),
}));

vi.mock("@/components/navigation/ConsoleLink", () => ({
  ConsoleLink: ({ href, children }: { href: string; children: ReactNode }) => (
    <a href={href}>{children}</a>
  ),
}));

beforeEach(() => {
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
  if (document.fonts == null) {
    Object.defineProperty(document, "fonts", {
      configurable: true,
      value: { addEventListener() {}, removeEventListener() {} },
    });
  }
});

function wrap(node: ReactNode) {
  return <MantineProvider>{node}</MantineProvider>;
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("SubchannelTriggerFields", () => {
  it("adds, edits, and removes typed parameters and sample_input", () => {
    let latest: Record<string, unknown> = { input: [], sample_input: {} };
    function Harness() {
      const [config, setConfig] = useState<Record<string, unknown>>(latest);
      return (
        <SubchannelTriggerFields
          config={config}
          editable
          onChange={(next) => {
            latest = next;
            setConfig(next);
          }}
        />
      );
    }

    render(wrap(<Harness />));
    expect(screen.getByText("No input parameters declared.")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Add parameter" }));
    const nameInput = screen.getByLabelText("Name");
    fireEvent.change(nameInput, { target: { value: "entity_id" } });
    expect(latest.input).toEqual([
      { name: "entity_id", type: "string", required: true },
    ]);

    fireEvent.click(screen.getByRole("button", { name: "Remove parameter" }));
    expect(latest.input).toEqual([]);
  });
});

describe("CallChannelFields", () => {
  it("loads published sub-channels, renders contract parameter inputs, and flags stale keys", async () => {
    vi.mocked(listChannels).mockResolvedValue({
      items: [
        {
          id: "ch_sub",
          name: "ISC Incremental Publisher",
          description: "",
          active: true,
          failure_streak: 0,
          draft_revision: 1,
          latest_version: {
            number: 2,
            published_at: "2026-11-26T00:00:00Z",
          },
          tags: [],
          created_at: "2026-11-26T00:00:00Z",
          updated_at: "2026-11-26T00:00:00Z",
        },
      ],
      total: 1,
      limit: 200,
      offset: 0,
    });
    vi.mocked(getVersion).mockResolvedValue({
      version: {
        id: "cv_2",
        channel_id: "ch_sub",
        number: 2,
        note: "",
        published_by_user_id: "u_1",
        published_at: "2026-11-26T00:00:00Z",
        graph: {
          settings: { run_timeout_sec: null, run_retry_limit: null, error_channel_id: null },
          nodes: [
            {
              id: "nd_trig",
              name: "Sub Trigger",
              ref: "sub_trigger",
              type: "trigger.subchannel",
              type_version: 1,
              position: { x: 0, y: 0 },
              config: {
                input: [
                  { name: "entity_id", type: "string", required: true, description: "Source entity" },
                  { name: "limit", type: "integer", required: false, default: 200 },
                ],
                sample_input: {},
              },
            },
          ],
          edges: [],
        },
      },
    });

    let latest: Record<string, unknown> = {
      channel_id: "ch_sub",
      inputs: { entity_id: "{{ $json.id }}", obsolete_param: "x" },
    };
    function Harness() {
      const [config, setConfig] = useState<Record<string, unknown>>(latest);
      return (
        <CallChannelFields
          currentChannelId="ch_parent"
          config={config}
          editable
          renderTemplateInput={({ name, label, description, omitted, value, onChange }) => (
            <label>
              <span>{label}</span>
              <span>{description}</span>
              <input
                aria-label={`param-${name}`}
                data-omitted={omitted ? "true" : "false"}
                value={value}
                onChange={(e) => onChange(e.currentTarget.value)}
              />
            </label>
          )}
          onChange={(next) => {
            latest = next;
            setConfig(next);
          }}
        />
      );
    }

    render(wrap(<Harness />));

    await waitFor(() => {
      expect(screen.getByLabelText("param-entity_id")).toBeTruthy();
    });
    expect(screen.getByText("entity_id")).toBeTruthy();
    expect(screen.getByText(/default: 200/)).toBeTruthy();
    expect(
      screen.getByText(
        "Stale input 'obsolete_param' is no longer declared on the target sub-channel.",
      ),
    ).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Remove stale input obsolete_param" }));
    expect(latest.inputs).toEqual({ entity_id: "{{ $json.id }}" });

    const limitInput = screen.getByLabelText("param-limit");
    expect(limitInput.getAttribute("data-omitted")).toBe("true");
    fireEvent.change(limitInput, { target: { value: "50" } });
    expect(latest.inputs).toEqual({ entity_id: "{{ $json.id }}", limit: "50" });
    expect(screen.getByLabelText("param-limit").getAttribute("data-omitted")).toBe("false");
    fireEvent.change(limitInput, { target: { value: "" } });
    expect(latest.inputs).toEqual({ entity_id: "{{ $json.id }}" });
    expect(screen.getByLabelText("param-limit").getAttribute("data-omitted")).toBe("true");
  });
});
