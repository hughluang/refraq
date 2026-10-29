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
import { Button, Code, Group, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useId, useRef } from "react";

import { FieldMarks } from "@/components/form/FieldChrome";
import type { FieldNote } from "@/components/form/fieldNotes";
import type { SchemaObject } from "@/features/channels/configSchemaForm";
import type { FieldMessage } from "@/features/channels/problemLabel";
import { RunErrorText } from "@/features/channels/RunErrorText";
import {
  TemplateRunPreview,
  type TemplatePreviewSource,
} from "@/features/channels/TemplateRunPreview";
import { scanTemplate } from "@/features/channels/templateScan";
import {
  resolvedText,
  templateCompletions,
  templatePreview,
  templateRule,
  typeBadge,
  typeMark,
  type RecordedField,
  type TemplatePreview,
  type TemplateValueSchema,
} from "@/features/channels/templateLogic";
import type { SelfScope } from "@/features/channels/templateScope";

export type TemplateCaret = {
  key: string;
  read: () => { text: string; head: number; from: number; to: number };
  write: (from: number, to: number, text: string) => void;
};

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
  /** Evaluates the field against a recorded run; `null` hides the preview. */
  runPreview?: TemplatePreviewSource | null;
  /** Execution Input for this field. Omitted until a sample has loaded. */
  recorded?: RecordedField;
  /** True after the text differs from the run snapshot. */
  edited?: boolean;
  /** Stable identity for the last focused template field. */
  caretKey?: string;
  onCaret?: (caret: TemplateCaret) => void;
  onCaretGone?: (key: string) => void;
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
  runPreview = null,
  recorded,
  edited = false,
  caretKey = "",
  onCaret,
  onCaretGone,
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
  const caretKeyRef = useRef(caretKey);
  const onCaretRef = useRef(onCaret);
  const onCaretGoneRef = useRef(onCaretGone);
  const editableRef = useRef(editable);
  const syncing = useRef(false);
  valueRef.current = value;
  onChangeRef.current = onChange;
  scopeRef.current = scope;
  caretKeyRef.current = caretKey;
  onCaretRef.current = onCaret;
  onCaretGoneRef.current = onCaretGone;
  editableRef.current = editable;
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
    const reportCaret = (view: EditorView) => {
      if (!editableRef.current || !onCaretRef.current) return;
      onCaretRef.current({
        key: caretKeyRef.current,
        read: () => {
          const range = view.state.selection.main;
          return {
            text: view.state.doc.toString(),
            head: range.head,
            from: range.from,
            to: range.to,
          };
        },
        write: (from, to, text) => {
          if (!editableRef.current) return;
          view.dispatch({
            changes: { from, to, insert: text },
            selection: EditorSelection.cursor(from + text.length),
          });
          view.focus();
        },
      });
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
            if (update.docChanged && !syncing.current) {
              onChangeRef.current(update.state.doc.toString());
            }
            if (
              update.view.hasFocus &&
              (update.focusChanged || update.selectionSet || update.docChanged)
            ) {
              reportCaret(update.view);
            }
          }),
          EditorView.domEventHandlers({
            focus: (_event, view) => {
              reportCaret(view);
            },
          }),
        ],
      }),
    });
    slots.current = { view, editable: editableSlot, aria: ariaSlot };
    return () => {
      const key = caretKeyRef.current;
      view.destroy();
      slots.current = null;
      onCaretGoneRef.current?.(key);
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
  const showPreview = edited && runPreview != null;
  const t = useTranslate();
  const badge = typeMark(t, typeBadge(valueSchema));
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
      {showPreview && runPreview ? (
        <TemplateRunPreview
          source={runPreview}
          text={value}
          scopeKey={JSON.stringify(scope.nodes.map((node) => [node.ref, node.name]))}
          raw={rule === "text"}
        />
      ) : recorded ? (
        <RecordedValue recorded={recorded} raw={rule === "text"} />
      ) : null}
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

function RecordedValue({ recorded, raw }: { recorded: RecordedField; raw: boolean }) {
  const t = useTranslate();
  let body;
  if (recorded.state === "absent") {
    body = (
      <Text size="xs" c="dimmed">
        {t("channels.template.recorded.absent")}
      </Text>
    );
  } else if (recorded.state === "error") {
    body = <RunErrorText code={recorded.code} message={recorded.message} />;
  } else {
    const text = raw && typeof recorded.value === "string" ? recorded.value : JSON.stringify(recorded.value, null, 2);
    body =
      text === "" ? (
        <Text size="xs" c="dimmed" fs="italic">
          {t("channels.template.preview.empty")}
        </Text>
      ) : (
        <Code block className="channel-template-field__recorded">
          {text}
        </Code>
      );
  }
  return (
    <div className="channel-template-field__preview">
      <Text size="xs" fw={500} c="dimmed">
        {t("channels.template.recorded.title")}
      </Text>
      {body}
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

