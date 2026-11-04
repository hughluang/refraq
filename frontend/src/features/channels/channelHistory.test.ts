import { describe, expect, it } from "vitest";

import { historyContext, historyReturn } from "./channelHistory";

describe("channel history context", () => {
  it("restores edit history and the selected page and filters", () => {
    const context = "run_origin=edit&run_status=failed&run_target=published&run_page=3";
    expect(historyReturn("chn_1", context)).toBe(
      "/console/channels/chn_1/edit?run_panel=runs&run_origin=edit&run_status=failed&run_target=published&run_page=3",
    );
  });

  it("defaults to show history and discards arbitrary navigation and invalid values", () => {
    expect(historyReturn("chn_1", "return=https://evil.test&run_origin=https://evil.test&run_status=invalid&run_target=other&run_page=-1")).toBe(
      "/console/channels/chn_1?run_panel=runs",
    );
    expect(historyContext("run_page=1e20&unknown=value")).toBe("run_panel=runs");
  });
});
