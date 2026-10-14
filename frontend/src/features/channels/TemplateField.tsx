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

import { FieldMarks } from "@/components/form/FieldChrome";
import type { FieldNote } from "@/components/form/fieldNotes";
import type { SchemaObject } from "@/features/channels/configSchemaForm";
import type { FieldMessage } from "@/features/channels/problemLabel";
import { scanTemplate } from "@/features/channels/templateScan";
import {
  resolvedText,
  templateCompletions,
  templatePreview,
  templateRule,
  typeBadge,
  type TemplatePreview,
  type TemplateValueSchema,
} from "@/features/channels/templateLogic";
import type { SelfScope } from "@/features/channels/templateScope";

type Props = {
  label?: string;
  ariaLabel?: string;
  description?: string;
  valueSchema: TemplateValueSchema | null;
  value: string;
  editable: boolean;
  scope: SelfScope;
  messages?: readonly FieldMessage[];
  openSignal?: string | null;
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
    outline: "none",
    borderColor: "var(--mantine-primary-color-filled)",
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
  scope,
  messages = [],
  openSignal = null,
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
  const scopeRef = useRef(scope);
  const syncing = useRef(false);
  valueRef.current = value;
  onChangeRef.current = onChange;
  scopeRef.current = scope;
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
        scopeRef.current,
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
  const tone = label
    ? invalid
      ? "error"
      : messages.some((message) => message.severity === "warning")
        ? "warning"
        : undefined
    : undefined;
  const notes = label ? templateNotes(t, messages, preview, !invalid) : [];

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
        <Group gap={4} wrap="nowrap">
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
          {label ? (
            <FieldMarks
              label={label}
              description={description}
              notes={notes}
              openSignal={openSignal}
              editSignal={value}
            />
          ) : null}
        </Group>
        {editable && label ? (
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
      {label && !description && rule === "text" ? (
        <Text size="xs" c="dimmed">
          {t("channels.template.ruleText")}
        </Text>
      ) : null}
      {label && !description && rule === "json" ? (
        <Text size="xs" c="dimmed">
          {t("channels.template.ruleJson")}
        </Text>
      ) : null}
    </div>
  );
}

function templateNotes(
  t: (key: string, options?: Record<string, unknown>) => string,
  messages: readonly FieldMessage[],
  preview: TemplatePreview,
  showMatch: boolean,
): FieldNote[] {
  const notes: FieldNote[] = messages.map((message) => ({
    text: message.text,
    tone: message.severity === "warning" ? "warning" : "error",
  }));
  if (preview.state === "error") {
    notes.push({ text: t("channels.template.parseFailed"), tone: "error" });
  } else if (preview.state === "invalid") {
    notes.push({ text: t("problems.CHANNEL_EXPRESSION_INVALID"), tone: "error" });
  } else if (showMatch && preview.state === "ok") {
    notes.push(
      { text: t("channels.template.parsed"), tone: "info" },
      { text: t("channels.template.resolved", { value: resolvedText(preview.value) }), tone: "info" },
    );
  } else if (preview.state === "string") {
    notes.push({ text: t("channels.template.resultString"), tone: "info" });
  } else if (preview.state === "deferred") {
    notes.push({ text: t("channels.template.checkedAtRun"), tone: "info" });
  }
  return notes;
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

