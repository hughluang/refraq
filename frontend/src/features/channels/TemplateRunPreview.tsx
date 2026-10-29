"use client";

import { Code, Group, Loader, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { RunErrorText } from "@/features/channels/RunErrorText";
import type {
  NodeSampleScopeInput,
  NodeSampleScopeLevel,
  TemplatePreviewResult,
} from "@/features/channels/types";
import { problemMessage } from "@/lib/problem";

/** Quiet time after an edit before the field is evaluated again. */
export const PREVIEW_PAUSE_MS = 400;

type PreviewPath = readonly (string | number)[];

/** Evaluates a channel's template fields against its latest draft run. */
export type ChannelTemplatePreview = {
  /** `null` while the channel has no draft run. */
  run: {
    /** Changes whenever the run records more. */
    key: string;
    evaluate: (
      nodeId: string,
      path: PreviewPath,
      scope?: readonly NodeSampleScopeInput[],
    ) => Promise<TemplatePreviewResult>;
  } | null;
};

type FieldRun = { key: string; evaluate: () => Promise<TemplatePreviewResult> };

/** One template field bound to a `ChannelTemplatePreview`. */
export type TemplatePreviewSource = {
  /** Identifies the field; another field starts a fresh preview. */
  target: string;
  run: FieldRun | null;
  nodeName: (nodeId: string) => string;
  /** Display time of the run this preview reads. Null when the run has not started. */
  runTime?: string | null;
};

export function bindTemplatePreview(
  preview: ChannelTemplatePreview,
  nodeId: string,
  path: PreviewPath,
  nodeName: (nodeId: string) => string,
  sampleScope?: readonly NodeSampleScopeInput[],
  runTime?: string | null,
): TemplatePreviewSource {
  const { run } = preview;
  const scopeKey = JSON.stringify(sampleScope ?? null);
  return {
    target: JSON.stringify([nodeId, path]),
    run: run
      ? {
          key: sampleScope === undefined ? run.key : `${run.key}|${scopeKey}`,
          evaluate: () =>
            sampleScope === undefined
              ? run.evaluate(nodeId, path)
              : run.evaluate(nodeId, path, sampleScope),
        }
      : null,
    nodeName,
    runTime: runTime ?? null,
  };
}

type Shown = { key: string; result: TemplatePreviewResult | null; error: unknown };

export function TemplateRunPreview({
  source,
  text,
  scopeKey,
  raw,
}: {
  source: TemplatePreviewSource;
  text: string;
  /** Changes when the nodes the template may name change. */
  scopeKey: string;
  /** Show a string value as its text rather than as JSON. */
  raw: boolean;
}) {
  const t = useTranslate();
  if (source.run == null) {
    return (
      <PreviewFrame pending={false}>
        <Text size="xs" c="dimmed">
          {t("channels.template.preview.noRun")}
        </Text>
      </PreviewFrame>
    );
  }
  return (
    <RecordedPreview
      key={source.target}
      run={source.run}
      text={text}
      scopeKey={scopeKey}
      raw={raw}
      nodeName={source.nodeName}
      runTime={source.runTime ?? null}
    />
  );
}

function RecordedPreview({
  run,
  text,
  scopeKey,
  raw,
  nodeName,
  runTime,
}: {
  run: FieldRun;
  text: string;
  scopeKey: string;
  raw: boolean;
  nodeName: (nodeId: string) => string;
  runTime: string | null;
}) {
  const t = useTranslate();
  const key = JSON.stringify([run.key, scopeKey, text]);
  const [shown, setShown] = useState<Shown | null>(null);
  const evaluateRef = useRef(run.evaluate);
  const asked = useRef(false);
  evaluateRef.current = run.evaluate;

  useEffect(() => {
    let live = true;
    const timer = window.setTimeout(
      () => {
        asked.current = true;
        evaluateRef.current().then(
          (result) => {
            if (live) setShown({ key, result, error: null });
          },
          (error: unknown) => {
            if (live) setShown({ key, result: null, error });
          },
        );
      },
      asked.current ? PREVIEW_PAUSE_MS : 0,
    );
    return () => {
      live = false;
      window.clearTimeout(timer);
    };
  }, [key]);

  let body;
  if (shown == null) {
    body = (
      <Text size="xs" c="dimmed">
        {t("channels.template.preview.pending")}
      </Text>
    );
  } else if (shown.result == null) {
    body = (
      <Text size="xs" c="red">
        {problemMessage(t, shown.error, t("channels.template.preview.unavailable"))}
      </Text>
    );
  } else {
    body = (
      <PreviewResult result={shown.result} raw={raw} nodeName={nodeName} runTime={runTime} />
    );
  }
  return <PreviewFrame pending={shown?.key !== key}>{body}</PreviewFrame>;
}

function PreviewFrame({ pending, children }: { pending: boolean; children: ReactNode }) {
  const t = useTranslate();
  return (
    <div className="channel-template-field__preview" aria-busy={pending}>
      <Group gap={6} wrap="nowrap">
        <Text size="xs" fw={500} c="dimmed">
          {t("channels.template.preview.title")}
        </Text>
        {pending ? <Loader size={10} /> : null}
      </Group>
      {children}
    </div>
  );
}

function PreviewResult({
  result,
  raw,
  nodeName,
  runTime,
}: {
  result: TemplatePreviewResult;
  raw: boolean;
  nodeName: (nodeId: string) => string;
  runTime: string | null;
}) {
  const t = useTranslate();
  const source = provenanceText(t, result.scope ?? [], nodeName, runTime);
  if (result.state === "failed") {
    return (
      <>
        <RunErrorText
          code={result.code}
          message={result.message}
          sentence={
            result.code === "CHANNEL_NODE_FAILED"
              ? t("channels.template.preview.failed")
              : undefined
          }
        />
        <Provenance text={source} />
      </>
    );
  }
  if (result.state === "missing") {
    return (
      <>
        {result.node_ids.length > 0 ? (
          <Text size="xs" c="dimmed">
            {t("channels.template.preview.missingNodes", {
              nodes: result.node_ids.map(nodeName).join(", "),
            })}
          </Text>
        ) : null}
        {result.context ? (
          <Text size="xs" c="dimmed">
            {t("channels.template.preview.missingContext")}
          </Text>
        ) : null}
        <Provenance text={source} />
      </>
    );
  }
  const text = valueText(result.value, raw);
  return (
    <>
      {text === "" ? (
        <Text size="xs" c="dimmed" fs="italic">
          {t("channels.template.preview.empty")}
        </Text>
      ) : (
        <Code block className="channel-template-field__value">
          {text}
        </Code>
      )}
      {result.truncated ? (
        <Text size="xs" c="dimmed">
          {t("channels.template.preview.truncated")}
        </Text>
      ) : null}
      <Provenance text={source} />
    </>
  );
}

function Provenance({ text }: { text: string | null }) {
  if (!text) return null;
  return (
    <Text size="xs" c="dimmed">
      {text}
    </Text>
  );
}

function provenanceText(
  t: (key: string, options?: Record<string, unknown>) => string,
  scope: readonly NodeSampleScopeLevel[],
  nodeName: (nodeId: string) => string,
  runTime: string | null,
): string | null {
  const rounds = scope
    .map((level) =>
      t("channels.template.preview.roundOf", {
        n: level.round + 1,
        name: nodeName(level.container_node_id),
      }),
    )
    .join(", ");
  if (rounds && runTime) return t("channels.template.preview.fromScope", { rounds, time: runTime });
  if (rounds) return t("channels.template.preview.fromScopeUntimed", { rounds });
  if (runTime) return t("channels.template.preview.fromRun", { time: runTime });
  return null;
}

function valueText(value: unknown, raw: boolean): string {
  if (raw && typeof value === "string") return value;
  return JSON.stringify(value, null, 2);
}
