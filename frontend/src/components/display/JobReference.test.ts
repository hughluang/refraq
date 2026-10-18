/** @vitest-environment jsdom */

import { MantineProvider } from "@mantine/core";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { createElement } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { JobReference } from "@/components/display/JobReference";

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
}

describe("JobReference", () => {
  beforeEach(() => {
    stubDomApis();
  });

  afterEach(() => {
    cleanup();
  });

  it("shows the status badge, translated kind, and id, and opens job detail", () => {
    const onOpen = vi.fn();
    render(
      createElement(
        MantineProvider,
        { env: "test" },
        createElement(JobReference, {
          jobId: "job_42",
          kind: "channel_run",
          status: "running",
          onOpen,
        }),
      ),
    );

    expect(screen.getByText("status.job.running")).toBeTruthy();
    expect(screen.getByText("jobs.kind.channel_run")).toBeTruthy();
    expect(screen.getByText("job_42")).toBeTruthy();
    expect(screen.queryByText("channel_run")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: /job_42/ }));
    expect(onOpen).toHaveBeenCalledWith("job_42");
  });

  it("uses a generic kind label when the kind is unknown", () => {
    render(
      createElement(
        MantineProvider,
        { env: "test" },
        createElement(JobReference, {
          jobId: "job_9",
          kind: "semantics_refresh",
          onOpen: vi.fn(),
        }),
      ),
    );

    expect(screen.getByText("jobs.kind.unknown")).toBeTruthy();
    expect(screen.queryByText("semantics_refresh")).toBeNull();
  });
});
