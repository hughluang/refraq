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

  it("keeps dataset node fields, reference labels, and dataset problem copy in both languages", () => {
    const keys = [
      "channelNodeTypes.volume.dataset_query.label",
      "channelNodeTypes.volume.dataset_query.summary",
      "channelNodeTypes.volume.materialize.label",
      "channelNodeTypes.volume.materialize.summary",
      "channelNodeTypes.volume.batch_read.label",
      "channelNodeTypes.volume.batch_read.summary",
      "channels.config.fields.volume.dataset_query.source",
      "channels.config.fields.volume.dataset_query.sql",
      "channels.config.fields.volume.dataset_query.statement_timeout_sec",
      "channels.config.fields.volume.materialize.items",
      "channels.config.fields.volume.batch_read.dataset",
      "channels.config.fields.volume.batch_read.batch_size",
      "channels.config.fields.write.entity.statement_timeout_sec",
      "channels.config.datasetReference",
      "channels.config.datasetOrList",
      "problems.CHANNEL_DATASET_UNAVAILABLE",
      "problems.CHANNEL_DATASET_QUOTA_EXCEEDED",
      "channels.run.dataset.reason.expired",
      "channels.run.dataset.reason.lost",
      "channels.run.dataset.reason.not_found",
      "channels.run.dataset.reason.foreign_run",
      "channels.run.previewOnly",
    ];
    const enMessages = en as Record<string, string>;
    const zhMessages = zh as Record<string, string>;
    for (const key of keys) {
      expect(enMessages[key], key).toBeTruthy();
      expect(zhMessages[key], key).toBeTruthy();
      expect(enMessages[key]).not.toBe(key);
    }
    expect(enMessages["channels.config.fields.volume.batch_read.dataset"]).not.toBe("dataset");
  });

  it("names Until, its fields, and the parent frame sentence in both languages", () => {
    const enMessages = en as Record<string, string>;
    const zhMessages = zh as Record<string, string>;
    expect(enMessages["channelNodeTypes.volume.until.label"]).toBe("Until");
    expect(enMessages["channelNodeTypes.volume.until.summary"]).toBe(
      "Runs its loop body again until a condition becomes true.",
    );
    expect(zhMessages["channelNodeTypes.volume.until.label"]).toBe("直到");
    expect(zhMessages["channelNodeTypes.volume.until.summary"]).toBe("重复运行循环体，直到条件成立。");
    expect(enMessages["channels.config.fields.volume.until.until"]).toBe("until");
    expect(zhMessages["channels.config.fields.volume.until.until"]).toBe("直到条件");
    expect(enMessages["channels.config.fields.volume.until.max_iterations"]).toBe("max_iterations");
    expect(zhMessages["channels.config.fields.volume.until.max_iterations"]).toBe("最大轮次");
    expect(enMessages["problems.CHANNEL_LOOP_BODY_INVALID.parent"]).toBe(
      "parent does not name a For, a Batch Read, or an Until",
    );
    expect(zhMessages["problems.CHANNEL_LOOP_BODY_INVALID.parent"]).toBe(
      "parent 必须指向循环、批量读取或直到",
    );
  });

  it("keeps template insert and recorded-value copy in both languages", () => {
    const keys = [
      "channels.template.focusRequired",
      "channels.template.recorded.title",
      "channels.template.recorded.absent",
      "channels.template.preview.roundOf",
      "channels.template.preview.fromScope",
      "channels.template.preview.fromScopeUntimed",
      "channels.template.preview.fromRun",
    ];
    const enMessages = en as Record<string, string>;
    const zhMessages = zh as Record<string, string>;
    for (const key of keys) {
      expect(enMessages[key], key).toBeTruthy();
      expect(zhMessages[key], key).toBeTruthy();
      expect(enMessages[key]).not.toBe(zhMessages[key]);
    }
  });
});
