"use client";

import { defaultKeymap, history, historyKeymap } from "@codemirror/commands";
import { Compartment, EditorState } from "@codemirror/state";
import { EditorView, keymap } from "@codemirror/view";
import { Group, Text } from "@mantine/core";
import { useEffect, useId, useRef } from "react";

import { FieldMarks } from "@/components/form/FieldChrome";
import type { FieldNote } from "@/components/form/fieldNotes";

type Props = {
  label: string;
  description?: string;
  value: string;
  editable: boolean;
  notes?: readonly FieldNote[];
  openSignal?: string | null;
  onChange: (value: string) => void;
};

const codeTheme = EditorView.theme({
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
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
    lineHeight: "1.45",
  },
  ".cm-content": {
    padding: "8px",
    minHeight: "8rem",
  },
  "&.cm-focused .cm-cursor": {
    borderLeftColor: "var(--mantine-color-text)",
  },
});

export function PythonCodeField({
  label,
  description,
  value,
  editable,
  notes = [],
  openSignal = null,
  onChange,
}: Props) {
  const fieldId = useId();
  const labelId = useId();
  const hostRef = useRef<HTMLDivElement>(null);
  const slots = useRef<{
    view: EditorView;
    editable: Compartment;
    aria: Compartment;
  } | null>(null);
  const valueRef = useRef(value);
  const onChangeRef = useRef(onChange);
  const syncing = useRef(false);
  valueRef.current = value;
  onChangeRef.current = onChange;
  const invalid = notes.some((note) => note.tone === "error");

  useEffect(() => {
    const parent = hostRef.current;
    if (!parent) return;
    const editableSlot = new Compartment();
    const ariaSlot = new Compartment();
    const view = new EditorView({
      parent,
      state: EditorState.create({
        doc: valueRef.current,
        extensions: [
          EditorView.lineWrapping,
          history(),
          keymap.of([...defaultKeymap, ...historyKeymap]),
          codeTheme,
          editableSlot.of(EditorView.editable.of(true)),
          ariaSlot.of(contentAttributes(fieldId, labelId, false)),
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
  }, [fieldId, labelId]);

  useEffect(() => {
    const slot = slots.current;
    if (!slot) return;
    slot.view.dispatch({
      effects: [
        slot.editable.reconfigure(EditorView.editable.of(editable)),
        slot.aria.reconfigure(contentAttributes(fieldId, labelId, invalid)),
      ],
    });
  }, [editable, invalid, fieldId, labelId]);

  useEffect(() => {
    const view = slots.current?.view;
    if (!view) return;
    const current = view.state.doc.toString();
    if (current === value) return;
    syncing.current = true;
    view.dispatch({ changes: { from: 0, to: current.length, insert: value } });
    syncing.current = false;
  }, [value]);

  return (
    <div className="channel-code-field">
      <Group gap={4} wrap="nowrap">
        <Text component="label" id={labelId} htmlFor={fieldId} size="sm" fw={500}>
          {label}
        </Text>
        <FieldMarks
          label={label}
          description={description}
          notes={notes}
          openSignal={openSignal}
          editSignal={value}
        />
      </Group>
      <div
        ref={hostRef}
        className="channel-code-field__editor"
        data-severity={invalid ? "error" : undefined}
      />
    </div>
  );
}

function contentAttributes(fieldId: string, labelId: string, invalid: boolean) {
  return EditorView.contentAttributes.of({
    id: fieldId,
    "aria-labelledby": labelId,
    spellcheck: "false",
    "aria-invalid": invalid ? "true" : "false",
  });
}
