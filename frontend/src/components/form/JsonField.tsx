"use client";

import { JsonInput, Stack, Text, type JsonInputProps } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import { useEffect, useRef, useState, type ReactNode } from "react";

import { FieldChrome } from "@/components/form/FieldChrome";
import { FieldMode } from "@/components/form/FieldMode";
import { collectNotes, type FieldChromeProps } from "@/components/form/fieldNotes";

export type JsonFieldProps = Omit<
  JsonInputProps,
  "disabled" | "readOnly" | "value" | "defaultValue" | "onChange" | "validationError" | "error"
> &
  FieldChromeProps & {
    editable: boolean;
    value: unknown;
    onChange: (value: unknown) => void;
    accept?: (value: unknown) => boolean;
    onEmpty?: () => void;
    invalidMessage?: string;
    hint?: ReactNode;
  };

function jsonText(value: unknown): string {
  if (typeof value === "string") return value;
  if (value === undefined) return "";
  try {
    return JSON.stringify(value, null, 2) ?? "";
  } catch {
    return "";
  }
}

function rejected(value: unknown, accept?: (value: unknown) => boolean): boolean {
  if (!accept) return false;
  if (typeof value === "string") {
    const trimmed = value.trim();
    if (trimmed === "") return false;
    try {
      return !accept(JSON.parse(trimmed));
    } catch {
      return true;
    }
  }
  return !accept(value);
}

export function JsonField({
  editable,
  notes,
  openSignal,
  bare = false,
  value,
  onChange,
  accept,
  onEmpty,
  invalidMessage,
  hint,
  ...props
}: JsonFieldProps) {
  const t = useTranslate();
  const formatted = jsonText(value);
  const [draft, setDraft] = useState(formatted);
  const [invalid, setInvalid] = useState(() => rejected(value, accept));
  const blurring = useRef(false);

  useEffect(() => {
    setDraft(jsonText(value));
    setInvalid(rejected(value, accept));
  }, [value, accept]);

  const commit = (text: string) => {
    const trimmed = text.trim();
    if (trimmed === "") {
      if (onEmpty) {
        setInvalid(false);
        setDraft("{}");
        onEmpty();
        return;
      }
      setInvalid(true);
      return;
    }
    let parsed: unknown;
    try {
      parsed = JSON.parse(trimmed);
    } catch {
      setInvalid(true);
      return;
    }
    if (accept && !accept(parsed)) {
      setInvalid(true);
      return;
    }
    setInvalid(false);
    onChange(parsed);
  };

  const message = invalid ? (invalidMessage ?? t("form.json.invalid")) : undefined;
  const merged = bare ? [] : collectNotes(message, notes);
  const shown = formatted === "" ? undefined : formatted;

  return (
    <FieldMode
      editable={editable}
      label={props.label}
      description={bare ? undefined : props.description}
      notes={merged}
      openSignal={openSignal}
      value={shown}
      style={props.style}
      w={props.w}
    >
      <FieldChrome
        label={props.label}
        description={props.description}
        notes={merged}
        required={props.required}
        id={props.id}
        openSignal={openSignal}
        editSignal={draft}
        bare={bare}
      >
        {({ id, invalid: marked }) => (
          <Stack gap={4}>
            {hint != null && hint !== "" ? (
              <Text size="xs" c="dimmed">
                {hint}
              </Text>
            ) : null}
            <JsonInput
              {...props}
              id={id}
              autosize
              formatOnBlur
              minRows={3}
              spellCheck={false}
              value={draft}
              onChange={(next) => {
                setDraft(next);
                if (blurring.current) return;
                setInvalid(false);
              }}
              onBlur={(event) => {
                blurring.current = true;
                commit(event.currentTarget.value);
                queueMicrotask(() => {
                  blurring.current = false;
                });
              }}
              label={undefined}
              description={undefined}
              error={marked || undefined}
              withAsterisk={false}
            />
          </Stack>
        )}
      </FieldChrome>
    </FieldMode>
  );
}
