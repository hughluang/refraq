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
      "channelNodeTypes.read.changes.label",
      "channelNodeTypes.read.changes.summary",
      "channelNodeTypes.read.source_query.label",
      "channelNodeTypes.read.source_query.summary",
      "channels.config.fields.read.changes.entity_id",
      "channels.config.fields.read.changes.entity_id.description",
      "channels.config.fields.read.changes.limit",
      "channels.config.fields.read.changes.limit.description",
      "channels.config.fields.read.changes.shape",
      "channels.config.fields.read.changes.shape.description",
      "channels.config.fields.read.changes.sources",
      "channels.config.fields.read.changes.sources.description",
      "channels.config.options.shape.entries",
      "channels.config.options.shape.net",
      "channels.view.metric.has_more",
      "channels.run.ignoreCheckpoints",
      "channels.run.ignoreCheckpointsHint",
      "channels.run.cursorAdvances",
      "channels.run.cursorStays",
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
      "channelNodeTypes.action.http.label",
      "channelNodeTypes.action.http.summary",
      "channels.config.fields.action.http.method",
      "channels.config.fields.action.http.method.description",
      "channels.config.fields.action.http.url",
      "channels.config.fields.action.http.url.description",
      "channels.config.fields.action.http.query",
      "channels.config.fields.action.http.query.description",
      "channels.config.fields.action.http.headers",
      "channels.config.fields.action.http.headers.description",
      "channels.config.fields.action.http.body_mode",
      "channels.config.fields.action.http.body_mode.description",
      "channels.config.fields.action.http.body",
      "channels.config.fields.action.http.body.description",
      "channels.config.fields.action.http.content_type",
      "channels.config.fields.action.http.content_type.description",
      "channels.config.fields.action.http.http_account_id",
      "channels.config.fields.action.http.http_account_id.description",
      "channels.config.fields.action.http.timeout_sec",
      "channels.config.fields.action.http.timeout_sec.description",
      "channels.config.fields.action.http.max_redirects",
      "channels.config.fields.action.http.max_redirects.description",
      "channels.config.fields.action.http.name",
      "channels.config.fields.action.http.name.description",
      "channels.config.fields.action.http.value",
      "channels.config.fields.action.http.value.description",
      "channels.config.options.body_mode.json",
      "channels.config.options.body_mode.raw",
      "channels.config.httpAccount.placeholder",
      "channels.config.httpAccount.missing",
      "channels.config.httpAccount.loadFailed",
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

  it("names Changes Dataset and states its limit in both languages", () => {
    const enMessages = en as Record<string, string>;
    const zhMessages = zh as Record<string, string>;
    const keys = [
      "channelNodeTypes.volume.changes_dataset.label",
      "channelNodeTypes.volume.changes_dataset.summary",
      "channels.config.fields.volume.changes_dataset.entity_id",
      "channels.config.fields.volume.changes_dataset.entity_id.description",
      "channels.config.fields.volume.changes_dataset.sources",
      "channels.config.fields.volume.changes_dataset.sources.description",
      "channels.config.fields.volume.changes_dataset.limit",
      "channels.config.fields.volume.changes_dataset.limit.description",
      "channels.config.fields.volume.changes_dataset.statement_timeout_sec",
      "channels.config.fields.volume.changes_dataset.statement_timeout_sec.description",
    ];
    for (const key of keys) {
      expect(enMessages[key], key).toBeTruthy();
      expect(zhMessages[key], key).toBeTruthy();
      expect(zhMessages[key]).not.toBe(enMessages[key]);
    }
    expect(enMessages["channelNodeTypes.volume.changes_dataset.label"]).toBe("Changes Dataset");
    expect(enMessages["channelNodeTypes.volume.changes_dataset.description"]).toBeUndefined();
    expect(zhMessages["channelNodeTypes.volume.changes_dataset.description"]).toBeUndefined();
    expect(enMessages["channels.config.fields.volume.changes_dataset.limit.description"]).toBe(
      "Maximum change-log entries scanned in one execution, including entries the source filter hides. Default 1000000. Range 1–10000000.",
    );
    expect(zhMessages["channels.config.fields.volume.changes_dataset.limit.description"]).toBe(
      "\u4e00\u6b21\u6267\u884c\u6700\u591a\u626b\u63cf\u7684\u53d8\u66f4\u65e5\u5fd7\u6761\u76ee\u6570\uff0c\u5305\u542b\u88ab\u6765\u6e90\u8fc7\u6ee4\u85cf\u6389\u7684\u6761\u76ee\u3002\u9ed8\u8ba4 1000000\u3002\u8303\u56f4 1\u201310000000\u3002",
    );
  });

  it("names Until, its fields, and the parent frame sentence in both languages", () => {
    const enMessages = en as Record<string, string>;
    const zhMessages = zh as Record<string, string>;
    expect(enMessages["channelNodeTypes.volume.until.label"]).toBe("Until");
    expect(enMessages["channelNodeTypes.volume.until.summary"]).toBe(
      "Runs its loop body again until a condition becomes true.",
    );
    expect(enMessages["channels.config.fields.volume.until.until"]).toBe("until");
    expect(enMessages["channels.config.fields.volume.until.max_iterations"]).toBe("max_iterations");
    expect(enMessages["problems.CHANNEL_LOOP_BODY_INVALID.parent"]).toBe(
      "parent does not name a For, a Batch Read, or an Until",
    );
    for (const key of [
      "channelNodeTypes.volume.until.label",
      "channelNodeTypes.volume.until.summary",
      "channels.config.fields.volume.until.until",
      "channels.config.fields.volume.until.max_iterations",
      "problems.CHANNEL_LOOP_BODY_INVALID.parent",
    ]) {
      expect(zhMessages[key]?.length).toBeGreaterThan(0);
      expect(zhMessages[key]).not.toBe(enMessages[key]);
    }
  });

  it("names Inbound, Respond, their fields, and the keeping boundary in both languages", () => {
    const enMessages = en as Record<string, string>;
    const zhMessages = zh as Record<string, string>;
    const keys = [
      "channelNodeTypes.trigger.inbound.label",
      "channelNodeTypes.trigger.inbound.summary",
      "channelNodeTypes.action.respond.label",
      "channelNodeTypes.action.respond.summary",
      "channels.config.fields.trigger.inbound.path",
      "channels.config.fields.trigger.inbound.path.description",
      "channels.config.fields.trigger.inbound.allow_get",
      "channels.config.fields.trigger.inbound.allow_get.description",
      "channels.config.fields.trigger.inbound.credential_id",
      "channels.config.fields.trigger.inbound.credential_id.description",
      "channels.config.fields.trigger.inbound.input",
      "channels.config.fields.trigger.inbound.input.description",
      "channels.config.fields.trigger.inbound.name",
      "channels.config.fields.trigger.inbound.input.type",
      "channels.config.fields.trigger.inbound.input.required",
      "channels.config.fields.trigger.inbound.event_id.from",
      "channels.config.fields.trigger.inbound.event_id.key",
      "channels.config.fields.trigger.inbound.dedup_window_sec",
      "channels.config.fields.trigger.inbound.dedup_window_sec.description",
      "channels.config.fields.trigger.inbound.max_in_flight",
      "channels.config.fields.trigger.inbound.max_in_flight.description",
      "channels.config.fields.trigger.inbound.response",
      "channels.config.fields.trigger.inbound.response.mode",
      "channels.config.fields.trigger.inbound.response.status",
      "channels.config.fields.trigger.inbound.response.content_type",
      "channels.config.fields.trigger.inbound.response.headers",
      "channels.config.fields.trigger.inbound.response.body.kind",
      "channels.config.fields.trigger.inbound.response.body.text",
      "channels.config.fields.trigger.inbound.response.body.from",
      "channels.config.fields.trigger.inbound.response.body.key",
      "channels.config.fields.trigger.inbound.response.wait_sec",
      "channels.config.fields.trigger.inbound.response.fallback.status",
      "channels.config.fields.trigger.inbound.response.fallback.body",
      "channels.config.fields.trigger.inbound.sample_request",
      "channels.config.fields.trigger.inbound.sample_request.method",
      "channels.config.fields.trigger.inbound.sample_request.headers",
      "channels.config.fields.trigger.inbound.sample_request.query",
      "channels.config.fields.trigger.inbound.sample_request.body",
      "channels.config.fields.trigger.inbound.value",
      "channels.config.fields.trigger.inbound.public_url",
      "channels.config.fields.trigger.inbound.copy_url",
      "channels.config.options.inbound_mode.immediate",
      "channels.config.options.inbound_mode.respond_node",
      "channels.config.options.inbound_kind.static",
      "channels.config.options.inbound_kind.echo",
      "channels.config.options.inbound_from.header",
      "channels.config.options.inbound_from.query",
      "channels.config.options.inbound_from.body",
      "channels.config.options.inbound_type.string",
      "channels.config.options.inbound_type.integer",
      "channels.config.options.inbound_type.number",
      "channels.config.options.inbound_type.boolean",
      "channels.config.options.inbound_type.object",
      "channels.config.options.inbound_type.array",
      "channels.config.fields.action.respond.status",
      "channels.config.fields.action.respond.status.description",
      "channels.config.fields.action.respond.content_type",
      "channels.config.fields.action.respond.content_type.description",
      "channels.config.fields.action.respond.headers",
      "channels.config.fields.action.respond.headers.description",
      "channels.config.fields.action.respond.body",
      "channels.config.fields.action.respond.body.description",
      "channels.config.fields.action.respond.name",
      "channels.config.fields.action.respond.value",
      "channels.settings.keepSucceededRuns",
      "channels.settings.keepSucceededRunsHint",
      "channels.settings.keepFailedRuns",
      "channels.settings.keepFailedRunsHint",
      "channels.settings.keepTestRuns",
      "channels.settings.keepTestRunsHint",
      "channels.settings.inboundKeepingBoundary",
    ];
    for (const key of keys) {
      expect(enMessages[key], key).toBeTruthy();
      expect(zhMessages[key], key).toBeTruthy();
      expect(zhMessages[key], key).not.toBe(enMessages[key]);
    }
    expect(enMessages["channelNodeTypes.trigger.inbound.label"]).toBe("Inbound");
    expect(enMessages["channelNodeTypes.trigger.inbound.summary"]).toBe(
      "Starts a run when a third party calls the published path.",
    );
    expect(enMessages["channelNodeTypes.action.respond.label"]).toBe("Respond");
    expect(enMessages["channelNodeTypes.action.respond.summary"]).toBe(
      "Builds the HTTP response for an Inbound Trigger.",
    );
    expect(enMessages["channels.settings.inboundKeepingBoundary"]).toBe(
      "Accepted requests then leave no record.",
    );
    expect(zhMessages["channelNodeTypes.trigger.inbound.label"]).toBe(
      "\u5165\u7ad9\u89e6\u53d1",
    );
    expect(zhMessages["channelNodeTypes.action.respond.label"]).toBe("\u5e94\u7b54");
    expect(zhMessages["channels.settings.inboundKeepingBoundary"]).toBe(
      "\u5df2\u63a5\u53d7\u7684\u8bf7\u6c42\u6b64\u540e\u4e0d\u7559\u4e0b\u8bb0\u5f55\u3002",
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
