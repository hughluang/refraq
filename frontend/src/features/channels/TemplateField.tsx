"use client";

import {
  autocompletion,
  completionKeymap,
  type CompletionSource,
} from "@codemirror/autocomplete";
import { defaultKeymap, history, historyKeymap } from "@codemirror/commands";
import { Compartment, EditorSelection, EditorState } from "@codemirror/state";
import {
  Decoration,
  EditorView,
  keymap,
  ViewPlugin,
  type DecorationSet,
  type ViewUpdate,
} from "@codemirror/view";
import { Button, Group, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useId, useRef } from "react";

import type { SchemaObject } from "@/features/channels/configSchemaForm";
import { problemColor, type FieldMessage } from "@/features/channels/problemLabel";
import { scanTemplate } from "@/features/channels/templateScan";
import {
  resolvedText,
  templateCompletions,
  templatePreview,
  templateRule,
  typeBadge,
  type TemplatePreview,
  type TemplateRule,
  type TemplateValueSchema,
  type UpstreamOutput,
} from "@/features/channels/templateLogic";

type Props = {
  label?: string;
  ariaLabel?: string;
  description?: string;
  valueSchema: TemplateValueSchema | null;
  value: string;
  editable: boolean;
  upstream?: readonly UpstreamOutput[];
  messages?: readonly FieldMessage[];
  onChange: (value: string) => void;
};

const templateMarks = ViewPlugin.fromClass(
  class {
    decorations: DecorationSet;

    constructor(view: EditorView) {
      this.decorations = marksFor(view.state.doc.toString());
    }

    update(update: ViewUpdate) {
      if (update.docChanged) this.decorations = marksFor(update.state.doc.toString());
    }
  },
  { decorations: (plugin) => plugin.decorations },
);

const templateTheme = EditorView.theme({
  "&": {
    border: "1px solid var(--mantine-color-default-border)",
    borderRadius: "var(--mantine-radius-default)",
    backgroundColor: "transparent",
    fontSize: "var(--mantine-font-size-sm)",
  },
  "&.cm-focused": {
    outline: "2px solid var(--mantine-primary-color-filled)",
    outlineOffset: "1px",
  },
  ".cm-scroller": {
    fontFamily: "inherit",
    lineHeight: "1.45",
  },
  ".cm-content": {
    padding: "8px",
    minHeight: "4.5rem",
  },
  "&.cm-focused .cm-cursor": {
    borderLeftColor: "var(--mantine-color-text)",
  },
});

export function TemplateField({
  label,
  ariaLabel,
  description,
  valueSchema,
  value,
  editable,
  upstream = [],
  messages = [],
  onChange,
}: Props) {
  const schema: SchemaObject | null =
    valueSchema && "from" in valueSchema ? null : valueSchema;
  const fieldId = useId();
  const hostRef = useRef<HTMLDivElement>(null);
  const slots = useRef<{
    view: EditorView;
    editable: Compartment;
    aria: Compartment;
  } | null>(null);
  const valueRef = useRef(value);
  const onChangeRef = useRef(onChange);
  const upstreamRef = useRef(upstream);
  const syncing = useRef(false);
  valueRef.current = value;
  onChangeRef.current = onChange;
  upstreamRef.current = upstream;
  const invalid = messages.some((message) => message.severity !== "warning");

  useEffect(() => {
    const parent = hostRef.current;
    if (!parent) return;
    const editableSlot = new Compartment();
    const ariaSlot = new Compartment();
    const source: CompletionSource = (context) => {
      const found = templateCompletions(
        context.state.doc.toString(),
        context.pos,
        context.explicit,
        upstreamRef.current,
      );
      if (!found) return null;
      return {
        from: found.from,
        options: found.options.map((option) => ({ label: option, apply: option })),
      };
    };
    const view = new EditorView({
      parent,
      state: EditorState.create({
        doc: valueRef.current,
        extensions: [
          EditorView.lineWrapping,
          history(),
          keymap.of([...completionKeymap, ...defaultKeymap, ...historyKeymap]),
          autocompletion({ override: [source] }),
          templateMarks,
          templateTheme,
          editableSlot.of(EditorView.editable.of(true)),
          ariaSlot.of(EditorView.contentAttributes.of({ id: fieldId })),
          EditorView.updateListener.of((update) => {
            if (!update.docChanged || syncing.current) return;
            onChangeRef.current(update.state.doc.toString());
          }),
        ],
      }),
    });
    slots.current = { view, editable: editableSlot, aria: ariaSlot };
    return () => {
      view.destroy();
      slots.current = null;
    };
  }, [fieldId]);

  useEffect(() => {
    const slot = slots.current;
    if (!slot) return;
    slot.view.dispatch({
      effects: [
        slot.editable.reconfigure(EditorView.editable.of(editable)),
        slot.aria.reconfigure(contentAttributes(fieldId, label, ariaLabel, invalid)),
      ],
    });
  }, [editable, label, ariaLabel, invalid, fieldId]);

  useEffect(() => {
    const view = slots.current?.view;
    if (!view) return;
    const current = view.state.doc.toString();
    if (current === value) return;
    syncing.current = true;
    view.dispatch({ changes: { from: 0, to: current.length, insert: value } });
    syncing.current = false;
  }, [value]);

  const preview = templatePreview(value, schema);
  const rule = templateRule(schema);
  const badge = typeBadge(valueSchema);
  const t = useTranslate();
  const tone = invalid
    ? "error"
    : messages.some((message) => message.severity === "warning")
      ? "warning"
      : undefined;

  const insertCalculation = () => {
    const view = slots.current?.view;
    if (!view) return;
    const range = view.state.selection.main;
    view.dispatch({
      changes: { from: range.from, to: range.to, insert: "{{  }}" },
      selection: EditorSelection.cursor(range.from + 3),
    });
    view.focus();
  };

  return (
    <div className="channel-template-field">
      <Group justify="space-between" wrap="nowrap" gap="xs">
        {label ? (
          <Text component="label" htmlFor={fieldId} size="sm" fw={500}>
            {label}{" "}
            <Text span size="xs" c="dimmed">
              {badge}
            </Text>
          </Text>
        ) : (
          <Text span size="xs" c="dimmed">
            {badge}
          </Text>
        )}
        {editable ? (
          <Button type="button" size="compact-xs" variant="subtle" onClick={insertCalculation}>
            {t("channels.template.insert")}
          </Button>
        ) : null}
      </Group>
      <div
        ref={hostRef}
        className="channel-template-field__editor"
        data-severity={tone}
      />
      {description ? (
        <Text size="xs" c="dimmed">
          {description}
        </Text>
      ) : null}
      {messages.map((message, index) => (
        <Text key={`${index}-${message.text}`} size="xs" c={problemColor(message.severity)}>
          {message.text}
        </Text>
      ))}
      <TemplateStatus
        preview={preview}
        rule={rule}
        showRule={!description}
        showMatch={!invalid}
      />
    </div>
  );
}

function contentAttributes(
  fieldId: string,
  label: string | undefined,
  ariaLabel: string | undefined,
  invalid: boolean,
) {
  const attrs: Record<string, string> = {
    id: fieldId,
    spellcheck: "false",
    "aria-invalid": invalid ? "true" : "false",
  };
  if (!label && ariaLabel) attrs["aria-label"] = ariaLabel;
  return EditorView.contentAttributes.of(attrs);
}

function marksFor(text: string): DecorationSet {
  const ranges = scanTemplate(text)
    .marks.map((mark) =>
      Decoration.mark({
        class:
          mark.kind === "delim"
            ? "channel-template-field__delim"
            : "channel-template-field__ref",
      }).range(mark.from, mark.to),
    )
    .sort((left, right) => left.from - right.from);
  return Decoration.set(ranges);
}

function TemplateStatus({
  preview,
  rule,
  showRule,
  showMatch,
}: {
  preview: TemplatePreview;
  rule: TemplateRule | null;
  showRule: boolean;
  showMatch: boolean;
}) {
  const t = useTranslate();
  return (
    <>
      {showRule && rule === "text" ? (
        <Text size="xs" c="dimmed">
          {t("channels.template.ruleText")}
        </Text>
      ) : null}
      {showRule && rule === "json" ? (
        <Text size="xs" c="dimmed">
          {t("channels.template.ruleJson")}
        </Text>
      ) : null}
      {preview.state === "error" ? (
        <Text size="xs" c="red">
          {t("channels.template.parseFailed")}
        </Text>
      ) : null}
      {preview.state === "invalid" ? (
        <Text size="xs" c="red">
          {t("problems.CHANNEL_EXPRESSION_INVALID")}
        </Text>
      ) : null}
      {showMatch && preview.state === "ok" ? (
        <Text size="xs" c="dimmed">
          {t("channels.template.parsed")}
        </Text>
      ) : null}
      {showMatch && preview.state === "ok" ? (
        <Text size="xs" c="dimmed">
          {t("channels.template.resolved", { value: resolvedText(preview.value) })}
        </Text>
      ) : null}
      {preview.state === "string" ? (
        <Text size="xs" c="dimmed">
          {t("channels.template.resultString")}
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
