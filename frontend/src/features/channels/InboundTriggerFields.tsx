"use client";

import { Button, Group, Stack, Text } from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";

import { JsonField } from "@/components/form/JsonField";
import { NumberField } from "@/components/form/NumberField";
import { SelectField } from "@/components/form/SelectField";
import { SwitchField } from "@/components/form/SwitchField";
import { TextField } from "@/components/form/TextField";
import { MapEditor } from "@/features/channels/MapEditor";
import { InboundCredentialField } from "@/features/inbound-credentials/InboundCredentialField";
import { copyText } from "@/lib/copy-text";

const JSON_TYPES = ["string", "integer", "number", "boolean", "object", "array"] as const;
const EVENT_FROM = ["header", "query", "body"] as const;

type Translate = (key: string, options?: { defaultValue?: string }) => string;

function record(value: unknown): Record<string, unknown> | null {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function text(t: Translate, key: string): string {
  return t(`channels.config.fields.trigger.inbound.${key}`);
}

function hint(t: Translate, key: string): string | undefined {
  const value = t(`channels.config.fields.trigger.inbound.${key}.description`, { defaultValue: "" });
  return value || undefined;
}

function optionLabel(t: Translate, group: string, value: string): string {
  return t(`channels.config.options.${group}.${value}`, { defaultValue: value });
}

function whole(value: number | string): number | undefined {
  if (typeof value === "number" && Number.isFinite(value)) return Math.trunc(value);
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return Math.trunc(parsed);
  }
  return undefined;
}

function responseOf(config: Record<string, unknown>): Record<string, unknown> {
  return record(config.response) ?? {};
}

function cleanResponse(
  mode: "immediate" | "respond_node",
  source: Record<string, unknown>,
  patch: Record<string, unknown>,
): Record<string, unknown> {
  const merged = { ...source, ...patch, mode };
  if (mode === "respond_node") {
    const next: Record<string, unknown> = { mode };
    if (typeof merged.wait_sec === "number") next.wait_sec = merged.wait_sec;
    const fallback = record(merged.fallback);
    if (fallback) next.fallback = fallback;
    return next;
  }
  const next: Record<string, unknown> = { mode };
  if (typeof merged.status === "number") next.status = merged.status;
  if (typeof merged.content_type === "string" && merged.content_type !== "") {
    next.content_type = merged.content_type;
  }
  const headers = record(merged.headers);
  if (headers) next.headers = headers;
  next.body = record(merged.body) ?? { kind: "static", text: "" };
  return next;
}

export function InboundTriggerFields({
  config,
  editable,
  publishedHookPath = null,
  onChange,
}: {
  config: Record<string, unknown>;
  editable: boolean;
  publishedHookPath?: string | null;
  onChange: (config: Record<string, unknown>) => void;
}) {
  const t = useTranslate();
  const { open } = useNotification();
  const response = responseOf(config);
  const mode = response.mode === "respond_node" ? "respond_node" : "immediate";
  const body = record(response.body) ?? {};
  const kind = body.kind === "echo" ? "echo" : "static";
  const eventId = record(config.event_id);
  const eventFrom = typeof eventId?.from === "string" ? eventId.from : "";
  const eventKey = typeof eventId?.key === "string" ? eventId.key : "";
  const sample = record(config.sample_request) ?? {};
  const inputRows = Array.isArray(config.input) ? config.input.filter(record) : [];
  const fallback = record(response.fallback) ?? {};
  const origin = typeof window === "undefined" ? "" : window.location.origin;
  const publicUrl = publishedHookPath ? `${origin}/api/hooks/${publishedHookPath}` : "";

  const write = (patch: Record<string, unknown>) => {
    const next = { ...config };
    for (const [key, value] of Object.entries(patch)) {
      if (value === undefined) delete next[key];
      else next[key] = value;
    }
    onChange(next);
  };

  const writeResponse = (patch: Record<string, unknown>) => {
    write({ response: cleanResponse(mode, response, patch) });
  };

  const writeSample = (patch: Record<string, unknown>) => {
    const next = { ...sample };
    for (const [key, value] of Object.entries(patch)) {
      if (value === undefined) delete next[key];
      else next[key] = value;
    }
    write({ sample_request: Object.keys(next).length === 0 ? undefined : next });
  };

  const writeEvent = (from: string, key: string) => {
    write({ event_id: from === "" && key === "" ? undefined : { from, key } });
  };

  const copyUrl = () => {
    void copyText(publicUrl)
      .then(() => {
        open?.({ type: "success", message: t("common.copy.success") });
      })
      .catch(() => {
        open?.({ type: "error", message: t("common.copy.failed") });
      });
  };

  return (
    <Stack gap="sm">
      {publicUrl ? (
        <Stack gap={4}>
          <Text size="sm" fw={500}>
            {text(t, "public_url")}
          </Text>
          <Group gap="xs" wrap="nowrap">
            <Text size="sm">{publicUrl}</Text>
            <Button type="button" size="compact-sm" variant="default" onClick={copyUrl}>
              {text(t, "copy_url")}
            </Button>
          </Group>
        </Stack>
      ) : null}
      <TextField
        editable={editable}
        label={text(t, "path")}
        description={hint(t, "path")}
        value={typeof config.path === "string" ? config.path : ""}
        onChange={(event) => write({ path: event.currentTarget.value })}
      />
      <SwitchField
        editable={editable}
        label={text(t, "allow_get")}
        description={hint(t, "allow_get")}
        checked={config.allow_get === true}
        onChange={(event) => write({ allow_get: event.currentTarget.checked })}
      />
      <InboundCredentialField
        label={text(t, "credential_id")}
        description={hint(t, "credential_id")}
        value={typeof config.credential_id === "string" ? config.credential_id : ""}
        editable={editable}
        onChange={(value) => write({ credential_id: typeof value === "string" ? value : "" })}
      />
      <Stack gap="xs" role="group" aria-label={text(t, "input")}>
        <Group justify="space-between">
          <Text size="sm" fw={500}>
            {text(t, "input")}
          </Text>
          {editable ? (
            <Button
              type="button"
              size="xs"
              variant="light"
              onClick={() =>
                write({ input: [...inputRows, { name: "", type: "string", required: false }] })
              }
            >
              {t("channels.config.addItem")}
            </Button>
          ) : null}
        </Group>
        {inputRows.map((row, index) => {
          const type = typeof row.type === "string" ? row.type : "string";
          return (
            <Group key={index} align="flex-end" wrap="nowrap">
              <TextField
                editable={editable}
                label={text(t, "name")}
                value={typeof row.name === "string" ? row.name : ""}
                onChange={(event) => {
                  const name = event.currentTarget.value;
                  write({
                    input: inputRows.map((item, itemIndex) =>
                      itemIndex === index ? { ...item, name } : item,
                    ),
                  });
                }}
              />
              <SelectField
                editable={editable}
                label={text(t, "input.type")}
                data={JSON_TYPES.map((item) => ({
                  value: item,
                  label: optionLabel(t, "inbound_type", item),
                }))}
                value={type}
                allowDeselect={false}
                onChange={(next) => {
                  if (!next) return;
                  write({
                    input: inputRows.map((item, itemIndex) =>
                      itemIndex === index ? { ...item, type: next } : item,
                    ),
                  });
                }}
              />
              <SwitchField
                editable={editable}
                label={text(t, "input.required")}
                checked={row.required === true}
                onChange={(event) => {
                  const required = event.currentTarget.checked;
                  write({
                    input: inputRows.map((item, itemIndex) =>
                      itemIndex === index ? { ...item, required } : item,
                    ),
                  });
                }}
              />
              {editable ? (
                <Button
                  type="button"
                  size="xs"
                  variant="subtle"
                  onClick={() => write({ input: inputRows.filter((_, itemIndex) => itemIndex !== index) })}
                >
                  {t("channels.config.removeItem")}
                </Button>
              ) : null}
            </Group>
          );
        })}
      </Stack>
      <SelectField
        editable={editable}
        label={text(t, "event_id.from")}
        description={hint(t, "event_id")}
        clearable
        data={EVENT_FROM.map((item) => ({
          value: item,
          label: optionLabel(t, "inbound_from", item),
        }))}
        value={EVENT_FROM.some((item) => item === eventFrom) ? eventFrom : null}
        onChange={(next) => writeEvent(next ?? "", eventKey)}
      />
      <TextField
        editable={editable}
        label={text(t, "event_id.key")}
        value={eventKey}
        onChange={(event) => writeEvent(eventFrom, event.currentTarget.value)}
      />
      <NumberField
        editable={editable}
        label={text(t, "dedup_window_sec")}
        description={hint(t, "dedup_window_sec")}
        min={60}
        max={604800}
        allowDecimal={false}
        clampBehavior="none"
        value={typeof config.dedup_window_sec === "number" ? config.dedup_window_sec : ""}
        onChange={(next) => {
          const parsed = whole(next);
          write({ dedup_window_sec: parsed });
        }}
      />
      <NumberField
        editable={editable}
        label={text(t, "max_in_flight")}
        description={hint(t, "max_in_flight")}
        min={1}
        max={1000}
        allowDecimal={false}
        clampBehavior="none"
        value={typeof config.max_in_flight === "number" ? config.max_in_flight : ""}
        onChange={(next) => write({ max_in_flight: whole(next) })}
      />
      <Stack gap="sm" role="group" aria-label={text(t, "response")}>
        <Text size="sm" fw={500}>
          {text(t, "response")}
        </Text>
        <SelectField
          editable={editable}
          label={text(t, "response.mode")}
          description={hint(t, "response")}
          data={[
            { value: "immediate", label: optionLabel(t, "inbound_mode", "immediate") },
            { value: "respond_node", label: optionLabel(t, "inbound_mode", "respond_node") },
          ]}
          value={mode}
          allowDeselect={false}
          onChange={(next) => {
            if (next !== "immediate" && next !== "respond_node") return;
            write({ response: cleanResponse(next, response, { mode: next }) });
          }}
        />
        {mode === "immediate" ? (
          <>
            <NumberField
              editable={editable}
              label={text(t, "response.status")}
              min={100}
              max={599}
              allowDecimal={false}
              clampBehavior="none"
              value={typeof response.status === "number" ? response.status : ""}
              onChange={(next) => {
                const parsed = whole(next);
                writeResponse(parsed === undefined ? { status: undefined } : { status: parsed });
              }}
            />
            <TextField
              editable={editable}
              label={text(t, "response.content_type")}
              value={typeof response.content_type === "string" ? response.content_type : ""}
              onChange={(event) => writeResponse({ content_type: event.currentTarget.value })}
            />
            <MapEditor
              label={text(t, "response.headers")}
              editable={editable}
              value={response.headers}
              nameLabel={text(t, "name")}
              valueLabel={text(t, "value")}
              onChange={(headers) => writeResponse({ headers })}
            />
            <SelectField
              editable={editable}
              label={text(t, "response.body.kind")}
              data={[
                { value: "static", label: optionLabel(t, "inbound_kind", "static") },
                { value: "echo", label: optionLabel(t, "inbound_kind", "echo") },
              ]}
              value={kind}
              allowDeselect={false}
              onChange={(next) => {
                if (next !== "static" && next !== "echo") return;
                const nextBody =
                  next === "echo"
                    ? {
                        kind: "echo",
                        from: body.from === "body" || body.from === "query" ? body.from : "query",
                        key: typeof body.key === "string" ? body.key : "",
                      }
                    : { kind: "static", text: typeof body.text === "string" ? body.text : "" };
                writeResponse({ body: nextBody });
              }}
            />
            {kind === "echo" ? (
              <>
                <SelectField
                  editable={editable}
                  label={text(t, "response.body.from")}
                  data={[
                    { value: "query", label: optionLabel(t, "inbound_from", "query") },
                    { value: "body", label: optionLabel(t, "inbound_from", "body") },
                  ]}
                  value={body.from === "body" || body.from === "query" ? body.from : null}
                  allowDeselect={false}
                  onChange={(next) => {
                    if (next !== "query" && next !== "body") return;
                    writeResponse({
                      body: { kind: "echo", from: next, key: typeof body.key === "string" ? body.key : "" },
                    });
                  }}
                />
                <TextField
                  editable={editable}
                  label={text(t, "response.body.key")}
                  value={typeof body.key === "string" ? body.key : ""}
                  onChange={(event) =>
                    writeResponse({
                      body: {
                        kind: "echo",
                        from: body.from === "body" ? "body" : "query",
                        key: event.currentTarget.value,
                      },
                    })
                  }
                />
              </>
            ) : (
              <TextField
                editable={editable}
                label={text(t, "response.body.text")}
                value={typeof body.text === "string" ? body.text : ""}
                onChange={(event) => writeResponse({ body: { kind: "static", text: event.currentTarget.value } })}
              />
            )}
          </>
        ) : (
          <>
            <NumberField
              editable={editable}
              label={text(t, "response.wait_sec")}
              min={1}
              max={30}
              allowDecimal={false}
              clampBehavior="none"
              value={typeof response.wait_sec === "number" ? response.wait_sec : ""}
              onChange={(next) => {
                const parsed = whole(next);
                writeResponse(parsed === undefined ? { wait_sec: undefined } : { wait_sec: parsed });
              }}
            />
            <NumberField
              editable={editable}
              label={text(t, "response.fallback.status")}
              min={100}
              max={599}
              allowDecimal={false}
              clampBehavior="none"
              value={typeof fallback.status === "number" ? fallback.status : ""}
              onChange={(next) => {
                const parsed = whole(next);
                const nextFallback = { ...fallback };
                if (parsed === undefined) delete nextFallback.status;
                else nextFallback.status = parsed;
                writeResponse({
                  fallback: Object.keys(nextFallback).length === 0 ? undefined : nextFallback,
                });
              }}
            />
            <TextField
              editable={editable}
              label={text(t, "response.fallback.body")}
              value={typeof fallback.body === "string" ? fallback.body : ""}
              onChange={(event) =>
                writeResponse({ fallback: { ...fallback, body: event.currentTarget.value } })
              }
            />
          </>
        )}
      </Stack>
      <Stack gap="sm" role="group" aria-label={text(t, "sample_request")}>
        <Text size="sm" fw={500}>
          {text(t, "sample_request")}
        </Text>
        <TextField
          editable={editable}
          label={text(t, "sample_request.method")}
          value={typeof sample.method === "string" ? sample.method : ""}
          onChange={(event) => writeSample({ method: event.currentTarget.value })}
        />
        <MapEditor
          label={text(t, "sample_request.headers")}
          editable={editable}
          value={sample.headers}
          nameLabel={text(t, "name")}
          valueLabel={text(t, "value")}
          onChange={(headers) => writeSample({ headers })}
        />
        <MapEditor
          label={text(t, "sample_request.query")}
          editable={editable}
          value={sample.query}
          nameLabel={text(t, "name")}
          valueLabel={text(t, "value")}
          onChange={(query) => writeSample({ query })}
        />
        <JsonField
          editable={editable}
          label={text(t, "sample_request.body")}
          value={sample.body}
          onEmpty={() => writeSample({ body: undefined })}
          onChange={(next) => writeSample({ body: next })}
        />
      </Stack>
    </Stack>
  );
}
