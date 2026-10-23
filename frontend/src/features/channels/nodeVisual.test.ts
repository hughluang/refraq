import { describe, expect, it } from "vitest";

import {
  AdjustmentsIcon,
  AlertIcon,
  BoltIcon,
  BoxIcon,
  CalendarTimeIcon,
  CodeIcon,
  CopyOffIcon,
  DatabaseIcon,
  DatabaseSearchIcon,
  FilterIcon,
  FormsIcon,
  HandFingerIcon,
  JoinIcon,
  LayoutRowsIcon,
  MailIcon,
  PlugConnectedIcon,
  RepeatIcon,
  SendIcon,
  SplitIcon,
  TableImportIcon,
  TablePlusIcon,
  VariableIcon,
  WebhookIcon,
} from "@/components/icons";
import { familyTint, nodeTypeIcon } from "@/features/channels/nodeVisual";

describe("familyTint", () => {
  it("tints the two ends of the graph and keeps the middle quiet", () => {
    expect(familyTint("trigger")).toBe("orange");
    expect(familyTint("read")).toBe("blue");
    expect(familyTint("transform")).toBe("gray");
    expect(familyTint("volume")).toBe("gray");
    expect(familyTint("state")).toBe("gray");
    expect(familyTint("write")).toBe("grape");
    expect(familyTint("action")).toBe("grape");
  });

  it("falls back to gray for an unknown family", () => {
    expect(familyTint("ingest")).toBe("gray");
    expect(familyTint("")).toBe("gray");
  });
});

describe("nodeTypeIcon", () => {
  it("names an icon for every catalog type", () => {
    const expected: [string, string, unknown][] = [
      ["trigger.manual", "trigger", HandFingerIcon],
      ["trigger.scheduled", "trigger", CalendarTimeIcon],
      ["trigger.error", "trigger", AlertIcon],
      ["read.sql", "read", DatabaseIcon],
      ["read.source_query", "read", PlugConnectedIcon],
      ["transform.set_fields", "transform", FormsIcon],
      ["transform.code", "transform", CodeIcon],
      ["transform.if", "transform", SplitIcon],
      ["transform.filter", "transform", FilterIcon],
      ["transform.merge", "transform", JoinIcon],
      ["transform.deduplicate", "transform", CopyOffIcon],
      ["volume.for", "volume", RepeatIcon],
      ["volume.dataset_query", "volume", DatabaseSearchIcon],
      ["volume.materialize", "volume", TablePlusIcon],
      ["volume.batch_read", "volume", LayoutRowsIcon],
      ["state.variable", "state", VariableIcon],
      ["write.entity", "write", TableImportIcon],
      ["action.webhook", "action", WebhookIcon],
      ["action.email", "action", MailIcon],
    ];
    for (const [type, family, icon] of expected) {
      expect(nodeTypeIcon(type, family), type).toBe(icon);
    }
  });

  it("falls back to the family icon for an unknown type", () => {
    expect(nodeTypeIcon("trigger.queue", "trigger")).toBe(BoltIcon);
    expect(nodeTypeIcon("read.api", "read")).toBe(DatabaseIcon);
    expect(nodeTypeIcon("transform.sort", "transform")).toBe(AdjustmentsIcon);
    expect(nodeTypeIcon("volume.batch", "volume")).toBe(RepeatIcon);
    expect(nodeTypeIcon("state.counter", "state")).toBe(VariableIcon);
    expect(nodeTypeIcon("write.file", "write")).toBe(TableImportIcon);
    expect(nodeTypeIcon("action.slack", "action")).toBe(SendIcon);
  });

  it("falls back to a neutral icon when neither type nor family is known", () => {
    expect(nodeTypeIcon("misc.thing", "misc")).toBe(BoxIcon);
  });
});
