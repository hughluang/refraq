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

  it("keeps code and source-query field copy in both languages", () => {
    const keys = [
      "channelNodeTypes.transform.code.label",
      "channelNodeTypes.transform.code.summary",
      "channelNodeTypes.read.source_query.label",
      "channelNodeTypes.read.source_query.summary",
      "channels.config.fields.transform.code.code",
      "channels.config.fields.transform.code.code.description",
      "channels.config.fields.transform.code.timeout_sec",
      "channels.config.fields.transform.code.timeout_sec.description",
      "channels.config.fields.read.source_query.source_id",
      "channels.config.fields.read.source_query.source_id.description",
      "channels.config.fields.read.source_query.sql",
      "channels.config.fields.read.source_query.sql.description",
      "channels.config.fields.read.source_query.row_cap",
      "channels.config.fields.read.source_query.row_cap.description",
      "channels.canvas.permissionRequired",
      "channels.node.permissionReadOnly",
      "channels.config.source.placeholder",
      "channels.config.source.loadFailed",
      "channels.config.fields.action.webhook.webhook_id",
      "channels.config.fields.action.webhook.webhook_id.description",
      "channels.config.fields.action.webhook.body",
      "channels.config.fields.action.webhook.body.description",
      "channels.config.webhook.placeholder",
      "channels.config.webhook.missing",
      "channels.config.webhook.loadFailed",
      "channels.config.fields.action.email.email_account_id",
      "channels.config.fields.action.email.email_account_id.description",
      "channels.config.fields.action.email.to",
      "channels.config.fields.action.email.to.description",
      "channels.config.fields.action.email.subject",
      "channels.config.fields.action.email.subject.description",
      "channels.config.fields.action.email.body",
      "channels.config.fields.action.email.body.description",
      "channels.config.emailAccount.placeholder",
      "channels.config.emailAccount.missing",
      "channels.config.emailAccount.loadFailed",
    ];
    const enMessages = en as Record<string, string>;
    const zhMessages = zh as Record<string, string>;
    for (const key of keys) {
      expect(enMessages[key]).toBeTruthy();
      expect(zhMessages[key]).toBeTruthy();
    }
  });
});
