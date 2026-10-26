/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, render, screen } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { RunExecutionBrowser } from "@/features/channels/RunExecutionBrowser";
import { EMPTY_GRAPH, type Graph } from "@/features/channels/types";
import { formatInstant } from "@/lib/datetime";
import {
  resetSessionStoreForTests,
  useSessionStore,
  type CurrentUser,
} from "@/providers/session-store";

const { translate } = vi.hoisted(() => ({
  translate: (key: string) => key,
}));

vi.mock("@refinedev/core", () => ({
  useNotification: () => ({ open: vi.fn() }),
  useTranslate: () => translate,
}));

const user: CurrentUser = {
  id: "usr_1",
  account: "ada",
  display_name: "Ada",
  email: null,
  locale: "en-US",
  display_timezone: "UTC",
  role_id: null,
  role_key: null,
  role_name: null,
  permissions: [],
  identity_source: "local",
};

const graph: Graph = {
  ...EMPTY_GRAPH,
  nodes: [
    {
      id: "write",
      ref: "write",
      type: "write.entity",
      name: "Write",
      position: { x: 0, y: 0 },
      config: {},
      on_error: "stop",
      retry: null,
    },
  ],
};

const STARTED = "2026-10-11T06:00:29Z";

function execution(startedAt: string) {
  return {
    seq: 1,
    node_id: "write",
    container_seq: null,
    round: null,
    status: "succeeded",
    started_at: startedAt,
    finished_at: "2026-10-11T06:01:00Z",
    output_bytes: 12,
    output_preview: null,
    output_truncated: false,
    preview_only: false,
    preview_totals: {},
    error_code: null,
    error_message: null,
    error_detail: null,
  };
}

function stubExecutions(startedAt: string, requestId: string) {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (String(url).includes("/time-zones")) {
        return new Response(JSON.stringify({ items: [{ id: "UTC", aliases: [] }] }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }
      return new Response(
        JSON.stringify({
          items: [execution(startedAt)],
          total: 1,
          limit: 50,
          offset: 0,
        }),
        {
          status: 200,
          headers: {
            "Content-Type": "application/json",
            "X-Request-ID": requestId,
          },
        },
      );
    }),
  );
}

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
  useSessionStore.setState({
    user,
    permissionsReady: true,
    identityError: null,
    signedOutLocally: false,
  });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  resetSessionStoreForTests();
});

it("shows the response started_at string on the execution row", async () => {
  stubExecutions(STARTED, "req-exec");

  render(
    createElement(
      MantineProvider,
      { env: "test" },
      createElement(RunExecutionBrowser, {
        channelId: "chn_1",
        jobId: "job_1",
        graph,
      }),
    ),
  );

  const shown = formatInstant(STARTED, { timeZone: "UTC", locale: "en-US" });
  expect(await screen.findByText(shown)).toBeTruthy();
  expect(screen.getByRole("button", { name: "Write" })).toBeTruthy();
});

it("keeps the rest of the row when started_at is illegal and shows the request id", async () => {
  stubExecutions("yesterday", "req-exec");

  render(
    createElement(
      MantineProvider,
      { env: "test" },
      createElement(RunExecutionBrowser, {
        channelId: "chn_1",
        jobId: "job_1",
        graph,
      }),
    ),
  );

  expect(await screen.findByText("problems.API_CONTRACT_INVALID")).toBeTruthy();
  expect(screen.getByText("common.requestId: req-exec")).toBeTruthy();
  expect(screen.getByRole("button", { name: "Write" })).toBeTruthy();
  expect(screen.getByText("channels.editor.status.succeeded")).toBeTruthy();
});
