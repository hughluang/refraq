"use client";

import { ActionIcon, Group, Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { StatusBadge } from "@/components/display/StatusBadge";
import type { FieldNote } from "@/components/form/fieldNotes";
import { SelectField } from "@/components/form/SelectField";
import { CloseIcon } from "@/components/icons";
import { ConsoleLink } from "@/components/navigation/ConsoleLink";
import { listChannels } from "@/features/channels/api";
import type { SchemaObject } from "@/features/channels/configSchemaForm";
import {
  parseSubchannelParamRows,
  type SubchannelContractParam,
  type SubchannelParamType,
} from "@/features/channels/SubchannelTriggerFields";
import type { Channel } from "@/features/channels/types";
import { usePublishedChannelVersion } from "@/features/channels/usePublishedChannelVersion";

export const DATASET_REFERENCE_SCHEMA: SchemaObject = {
  type: "object",
  "x-refraq-dataset-reference": true,
  required: ["dataset_id", "columns", "count"],
  properties: {
    dataset_id: { type: "string" },
    columns: { type: "array" },
    count: { type: "integer" },
  },
};

export function subchannelParamSchema(param: SubchannelContractParam): SchemaObject {
  const nonNull = param.required || param.hasDefault;
  if (param.type === "dataset") {
    return nonNull
      ? DATASET_REFERENCE_SCHEMA
      : { ...DATASET_REFERENCE_SCHEMA, type: ["object", "null"] };
  }
  return nonNull ? { type: param.type } : { type: [param.type, "null"] };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export const SUBCHANNEL_PARAM_NAME_RE = /^[A-Za-z_][A-Za-z0-9_]{0,63}$/;

export function extractSubchannelParams(graph: unknown): SubchannelContractParam[] | null {
  if (!isRecord(graph) || !Array.isArray(graph.nodes)) return null;
  const triggers = graph.nodes.filter(
    (node): node is Record<string, unknown> =>
      isRecord(node) && typeof node.type === "string" && node.type.startsWith("trigger."),
  );
  if (triggers.length !== 1 || triggers[0]?.type !== "trigger.subchannel") return null;
  const triggerConfig = isRecord(triggers[0].config) ? triggers[0].config : {};
  const seen = new Set<string>();
  const params: SubchannelContractParam[] = [];
  for (const row of parseSubchannelParamRows(triggerConfig.input)) {
    if (!SUBCHANNEL_PARAM_NAME_RE.test(row.name) || seen.has(row.name)) continue;
    seen.add(row.name);
    params.push(row);
  }
  return params;
}

export function CallChannelFields({
  currentChannelId = null,
  config,
  editable,
  channelNotes = [],
  renderTemplateInput,
  onChange,
}: {
  currentChannelId?: string | null;
  config: Record<string, unknown>;
  editable: boolean;
  channelNotes?: readonly FieldNote[];
  renderTemplateInput: (args: {
    name: string;
    label: string;
    description: string;
    required: boolean;
    omitted: boolean;
    value: string;
    valueSchema: SchemaObject;
    onChange: (next: string) => void;
  }) => ReactNode;
  onChange: (config: Record<string, unknown>) => void;
}) {
  const t = useTranslate();
  const [channels, setChannels] = useState<Channel[]>([]);
  const [loadFailed, setLoadFailed] = useState(false);

  useEffect(() => {
    let active = true;
    setLoadFailed(false);
    void listChannels({
      published_trigger_type: "trigger.subchannel",
      limit: 200,
    })
      .then((page) => {
        if (active) setChannels(page.items);
      })
      .catch(() => {
        if (active) setLoadFailed(true);
      });
    return () => {
      active = false;
    };
  }, []);

  const selectedId = typeof config.channel_id === "string" ? config.channel_id : "";
  const inputsMap = isRecord(config.inputs) ? config.inputs : {};

  const eligible = useMemo(
    () => channels.filter((channel) => channel.id !== currentChannelId),
    [channels, currentChannelId],
  );
  const selectedChannel = eligible.find((channel) => channel.id === selectedId) ?? null;
  const latestNumber = selectedChannel?.latest_version?.number ?? null;
  const publishedVersion = usePublishedChannelVersion(selectedId, latestNumber, 0);
  const contractParams = useMemo(
    () => (publishedVersion?.graph ? extractSubchannelParams(publishedVersion.graph) : null),
    [publishedVersion],
  );

  const options = useMemo(() => {
    const base = eligible.map((channel) => ({
      value: channel.id,
      label: channel.active
        ? channel.name
        : `${channel.name} (${t("channels.config.subchannel.inactiveSuffix")})`,
    }));
    if (selectedId && !base.some((item) => item.value === selectedId)) {
      base.unshift({
        value: selectedId,
        label: `${selectedId} (${t("channels.config.subchannel.missing")})`,
      });
    }
    return base;
  }, [eligible, selectedId, t]);

  const setInputKey = (param: SubchannelContractParam, nextValue: string) => {
    const nextInputs: Record<string, unknown> = { ...inputsMap };
    if (!param.required && nextValue === "") {
      delete nextInputs[param.name];
    } else {
      nextInputs[param.name] = nextValue;
    }
    onChange({
      ...config,
      inputs: nextInputs,
    });
  };

  const removeInputKey = (name: string) => {
    const nextInputs = { ...inputsMap };
    delete nextInputs[name];
    onChange({
      ...config,
      inputs: nextInputs,
    });
  };

  const declaredNames = new Set((contractParams ?? []).map((item) => item.name));
  const staleKeys = contractParams
    ? Object.keys(inputsMap).filter((key) => !declaredNames.has(key))
    : [];

  const selectNotes: readonly FieldNote[] = loadFailed
    ? [{ text: t("channels.config.subchannel.loadFailed"), tone: "error" }, ...channelNotes]
    : channelNotes;

  return (
    <Stack gap="sm">
      <SelectField
        editable={editable}
        label={t("channels.config.fields.action.call_channel.channel_id")}
        description={t("channels.config.fields.action.call_channel.channel_id.description")}
        placeholder={t("channels.config.subchannel.placeholder")}
        data={options}
        value={selectedId || null}
        searchable
        notes={selectNotes}
        onChange={(next) =>
          onChange({
            ...config,
            channel_id: next ?? "",
          })
        }
      />
      {selectedId ? (
        <Group justify="space-between" align="center">
          <ConsoleLink href={`/console/channels/${encodeURIComponent(selectedId)}`}>
            <Text size="xs" span>
              {t("channels.config.subchannel.openTarget")}
            </Text>
          </ConsoleLink>
          {selectedChannel && !selectedChannel.active ? (
            <StatusBadge
              size="xs"
              tone="warning"
              labelKey="channels.config.subchannel.inactiveBadge"
            />
          ) : null}
        </Group>
      ) : null}
      {selectedId && contractParams ? (
        <Stack gap="xs" role="group" aria-label={t("channels.config.fields.action.call_channel.inputs")}>
          <Text size="sm" fw={500}>
            {t("channels.config.fields.action.call_channel.inputs")}
          </Text>
          {contractParams.length === 0 ? (
            <Text size="xs" c="dimmed">
              {t("channels.config.subchannel.targetNoParameters")}
            </Text>
          ) : (
            contractParams.map((param) => {
              const typeText = t(
                `channels.config.options.subchannel_type.${param.type}`,
                { defaultValue: param.type },
              );
              const defaultHint = param.hasDefault
                ? ` (${t("channels.config.subchannel.defaultHint", {
                    value: JSON.stringify(param.defaultValue),
                  })})`
                : "";
              const descParts = [
                `${typeText}${defaultHint}`,
                param.description.trim(),
              ].filter(Boolean);
              const hasExplicit = Object.prototype.hasOwnProperty.call(inputsMap, param.name);
              const rawVal = inputsMap[param.name];
              return (
                <div key={param.name}>
                  {renderTemplateInput({
                    name: param.name,
                    label: param.name,
                    description: descParts.join(" · "),
                    required: param.required,
                    omitted: !param.required && !hasExplicit,
                    value: typeof rawVal === "string" ? rawVal : "",
                    valueSchema: subchannelParamSchema(param),
                    onChange: (next) => setInputKey(param, next),
                  })}
                </div>
              );
            })
          )}
          {staleKeys.map((key) => (
            <Group key={key} justify="space-between" align="center" gap="xs">
              <Text size="xs" c="red">
                {t("channels.config.subchannel.staleInput", { name: key })}
              </Text>
              {editable ? (
                <ActionIcon
                  type="button"
                  size="xs"
                  variant="subtle"
                  color="red"
                  aria-label={t("channels.config.subchannel.removeStaleInput", { name: key })}
                  onClick={() => removeInputKey(key)}
                >
                  <CloseIcon size={12} />
                </ActionIcon>
              ) : null}
            </Group>
          ))}
        </Stack>
      ) : null}
    </Stack>
  );
}
