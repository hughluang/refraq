import { describe, expect, it } from "vitest";

import en from "@/locales/en-US/common.json";
import zh from "@/locales/zh-CN/common.json";

const PREFIX = "channelNodeTypes.";

function channelNodeTypeKeys(messages: Record<string, string>): string[] {
  return Object.keys(messages)
    .filter((key) => key.startsWith(PREFIX))
    .sort();
}

describe("channel node type locales", () => {
  it("keeps label and summary keys aligned across languages", () => {
    const enMessages = en as Record<string, string>;
    const zhMessages = zh as Record<string, string>;
    const enKeys = channelNodeTypeKeys(enMessages);
    const zhKeys = channelNodeTypeKeys(zhMessages);
    expect(zhKeys).toEqual(enKeys);
    expect(enKeys.length).toBeGreaterThan(0);

    const types = new Set(
      enKeys.map((key) => key.slice(PREFIX.length).replace(/\.(label|summary)$/, "")),
    );
    for (const type of types) {
      expect(enKeys).toContain(`${PREFIX}${type}.label`);
      expect(enKeys).toContain(`${PREFIX}${type}.summary`);
    }
    for (const key of enKeys) {
      expect(enMessages[key]).not.toBe("");
      expect(zhMessages[key]).not.toBe("");
    }
  });
});
