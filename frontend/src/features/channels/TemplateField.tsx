"use client";

import { Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useId, useMemo, useState } from "react";

import {
  applyCompletion,
  completionLabels,
  completionQuery,
  resolvedText,
  templatePreview,
  templateRule,
  typeBadge,
  type TemplatePreview,
  type TemplateRule,
  type TemplateValueSchema,
  type UpstreamOutput,
} from "@/features/channels/templateLogic";
import type { SchemaObject } from "@/features/channels/configSchemaForm";

type Props = {
  label?: string;
  ariaLabel?: string;
  valueSchema: TemplateValueSchema | null;
  value: string;
  editable: boolean;
  upstream?: readonly UpstreamOutput[];
  error?: string;
  onChange: (value: string) => void;
};

export function TemplateField({
  label,
  ariaLabel,
  valueSchema,
  value,
  editable,
  upstream = [],
  error,
  onChange,
}: Props) {
  const fieldId = useId();
  const [cursor, setCursor] = useState(value.length);
  const [open, setOpen] = useState(false);
  const schema: SchemaObject | null =
    valueSchema && "from" in valueSchema ? null : valueSchema;
  const preview = templatePreview(value, schema);
  const rule = templateRule(schema);
  const query = open ? completionQuery(value, cursor) : null;
  const labels = useMemo(
    () => (query ? completionLabels(query, upstream) : []),
    [query, upstream],
  );
  const badge = typeBadge(schema ?? valueSchema);

  if (!editable) {
    return (
      <div className="channel-template-field">
        {label ? (
          <Text size="sm" fw={500}>
            {label}
          </Text>
        ) : null}
        <pre className="channel-template-field__readonly">{value === "" ? "—" : value}</pre>
        <TemplateStatus preview={preview} rule={rule} />
      </div>
    );
  }

  return (
    <div className="channel-template-field">
      {label ? (
        <Text component="label" htmlFor={fieldId} size="sm" fw={500}>
          {label}{" "}
          <Text span size="xs" c="dimmed">
            {badge}
          </Text>
        </Text>
        ) : null}
      <div className="channel-template-field__editor">
        <pre aria-hidden className="channel-template-field__highlight">
          {highlight(value)}
          {value.endsWith("\n") || value === "" ? " " : null}
        </pre>
        <textarea
          id={fieldId}
          className="channel-template-field__input"
          aria-label={label ? undefined : ariaLabel}
          value={value}
          spellCheck={false}
          onChange={(event) => {
            const next = event.currentTarget.value;
            const nextCursor = event.currentTarget.selectionStart ?? next.length;
            onChange(next);
            setCursor(nextCursor);
            setOpen(completionQuery(next, nextCursor) != null);
          }}
          onSelect={(event) => {
            const nextCursor = event.currentTarget.selectionStart ?? value.length;
            setCursor(nextCursor);
            setOpen(completionQuery(value, nextCursor) != null);
          }}
          onBlur={() => {
            setOpen(false);
          }}
          aria-invalid={error ? true : undefined}
        />
      </div>
      {error ? (
        <Text size="xs" c="red">
          {error}
        </Text>
      ) : null}
      <TemplateStatus preview={preview} rule={rule} />
      {open && labels.length > 0 && query ? (
        <div className="channel-template-field__menu" role="listbox">
          {labels.map((item) => (
            <button
              key={item}
              type="button"
              role="option"
              className="channel-template-field__option"
              onMouseDown={(event) => {
                event.preventDefault();
                const applied = applyCompletion(value, cursor, query, item);
                onChange(applied.next);
                setCursor(applied.cursor);
                setOpen(false);
              }}
            >
              {query.kind === "ref" ? `self.${item}` : `self.${query.ref}.${item}`}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

function TemplateStatus({
  preview,
  rule,
}: {
  preview: TemplatePreview;
  rule: TemplateRule | null;
}) {
  const t = useTranslate();
  return (
    <>
      {rule === "text" ? (
        <Text size="xs" c="dimmed">
          {t("channels.template.ruleText")}
        </Text>
      ) : null}
      {rule === "json" ? (
        <Text size="xs" c="dimmed">
          {t("channels.template.ruleJson")}
        </Text>
      ) : null}
      {preview.state === "error" ? (
        <Text size="xs" c="red">
          {t("channels.template.parseFailed")}
        </Text>
      ) : null}
      {preview.state === "ok" ? (
        <Text size="xs" c="dimmed">
          {t("channels.template.parsed")}
        </Text>
      ) : null}
      {preview.state === "ok" ? (
        <Text size="xs" c="dimmed">
          {t("channels.template.resolved", { value: resolvedText(preview.value) })}
        </Text>
      ) : null}
      {preview.state === "deferred" ? (
        <Text size="xs" c="dimmed">
          {t("channels.template.checkedAtRun")}
        </Text>
      ) : null}
    </>
  );
}

function highlight(text: string) {
  const parts = text.split(/(\{\{|\}\}|\\\{\{)/g);
  return parts.map((part, index) => {
    if (part === "{{" || part === "}}" || part === "\\{{") {
      return (
        <span key={`${index}-${part}`} className="channel-template-field__mark">
          {part}
        </span>
      );
    }
    return <span key={`${index}-text`}>{part}</span>;
  });
}
