import { describe, expect, it } from "vitest";

import {
  presentCatalogPresence,
  presentCatalogSemantics,
  presentChannelActive,
  presentDictionaryStatus,
  presentEntityStatus,
  presentIdentityProviderEnabled,
  presentIndexStatus,
  presentJobStatus,
  presentModelServiceOpen,
  presentModelServiceUse,
  presentNodeStatus,
  presentProblemSeverity,
  presentPublishStatus,
  presentSourceStatus,
  presentStructureDiffClass,
  presentTokenStatus,
  presentTypeMappingOrigin,
  TONES,
  toneMantineColor,
  toneVariable,
} from "@/components/display/statusTone";

describe("status tone registry", () => {
  it("uses one tone for running on jobs, channel runs, and nodes", () => {
    expect(presentJobStatus("running").tone).toBe("running");
    expect(presentNodeStatus("running").tone).toBe("running");
    expect(presentPublishStatus("publishing").tone).toBe("running");
    expect(toneVariable("running")).toBe("var(--refraq-tone-running)");
    expect(toneMantineColor("running")).toBe("cyan");
  });

  it("maps each domain value to a tone and a label key", () => {
    expect(presentJobStatus("queued")).toEqual({
      tone: "info",
      labelKey: "status.job.queued",
    });
    expect(presentJobStatus("succeeded").tone).toBe("success");
    expect(presentJobStatus("failed").tone).toBe("danger");
    expect(presentJobStatus("cancelled").tone).toBe("neutral");
    expect(presentNodeStatus("skipped").tone).toBe("neutral");
    expect(presentNodeStatus("dead").labelKey).toBe("channels.run.notRun");
    expect(presentEntityStatus("serving").tone).toBe("success");
    expect(presentEntityStatus("deprecated").tone).toBe("danger");
    expect(presentDictionaryStatus(true).tone).toBe("danger");
    expect(presentTokenStatus("deactivated").tone).toBe("warning");
    expect(presentSourceStatus("active")).toEqual({
      tone: "success",
      labelKey: "sources.status.active",
    });
    expect(presentSourceStatus("disabled").tone).toBe("neutral");
    expect(presentStructureDiffClass("breaking").tone).toBe("danger");
    expect(presentStructureDiffClass("non_breaking").tone).toBe("info");
    expect(presentChannelActive(false).labelKey).toBe("channels.status.inactive");
    expect(presentCatalogPresence(false).tone).toBe("neutral");
    expect(presentCatalogSemantics(true).tone).toBe("success");
    expect(presentIdentityProviderEnabled(true).tone).toBe("success");
    expect(presentModelServiceUse(false).labelKey).toBe("modelServices.status.draft");
    expect(presentModelServiceOpen(true).tone).toBe("neutral");
    expect(presentIndexStatus("indexing").tone).toBe("running");
    expect(presentIndexStatus("failed").tone).toBe("danger");
    expect(presentTypeMappingOrigin("job").tone).toBe("warning");
    expect(presentTypeMappingOrigin("user").tone).toBe("info");
    expect(presentProblemSeverity("warning")).toBe("warning");
    expect(presentProblemSeverity("error")).toBe("danger");
  });

  it("does not surface an unknown status string as its label", () => {
    expect(presentJobStatus("nope")).toEqual({
      tone: "neutral",
      labelKey: "status.unknown",
    });
    expect(presentNodeStatus("nope").labelKey).toBe("status.unknown");
    expect(TONES).toContain("running");
  });
});
