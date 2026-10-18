"use client";

import { Input, Popover, Stack, Text } from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import {
  createContext,
  useContext,
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  useState,
  type ReactNode,
} from "react";

import "./field-chrome.css";
import { InfoIcon, StatusDotIcon } from "@/components/icons";
import {
  noteTone,
  orderedNotes,
  presentDescription,
  type FieldNote,
  type FieldTone,
} from "@/components/form/fieldNotes";

export type FieldDisclosureMode = "quiet" | "open-once";

export const FieldDisclosureContext = createContext<FieldDisclosureMode>("open-once");

const HOVER_CLOSE_MS = 120;

type MarkProps = {
  label?: string;
  description?: ReactNode;
  notes: readonly FieldNote[];
  openSignal?: string | null;
  editSignal?: unknown;
};

export function FieldMarks({
  label,
  description,
  notes,
  openSignal = null,
  editSignal,
}: MarkProps) {
  const shown = presentDescription(description);
  if (shown == null && notes.length === 0) return null;
  return (
    <span className="field-marks">
      {shown != null ? (
        <DescriptionMark label={label} description={shown} />
      ) : null}
      {notes.length > 0 ? (
        <StatusMark
          label={label}
          notes={notes}
          openSignal={openSignal}
          editSignal={editSignal}
        />
      ) : null}
    </span>
  );
}

function DescriptionMark({
  label,
  description,
}: {
  label?: string;
  description: ReactNode;
}) {
  const t = useTranslate();
  const [opened, setOpened] = useState(false);
  const pinned = useRef(false);
  const timer = useRef<number | null>(null);
  const clearTimer = () => {
    if (timer.current == null) return;
    window.clearTimeout(timer.current);
    timer.current = null;
  };
  useEffect(() => () => clearTimer(), []);

  const enter = () => {
    clearTimer();
    setOpened(true);
  };
  const leave = () => {
    clearTimer();
    timer.current = window.setTimeout(() => {
      timer.current = null;
      if (!pinned.current) setOpened(false);
    }, HOVER_CLOSE_MS);
  };
  const toggle = () => {
    if (opened && pinned.current) {
      pinned.current = false;
      setOpened(false);
      return;
    }
    pinned.current = true;
    setOpened(true);
  };
  const caption = t("form.field.description");
  return (
    <MarkPopover
      opened={opened}
      name={label ? `${label} ${caption}` : caption}
      tone="description"
      icon="info"
      onEnter={enter}
      onLeave={leave}
      onToggle={toggle}
      onDismiss={() => {
        pinned.current = false;
        setOpened(false);
      }}
    >
      <Text size="xs">{description}</Text>
    </MarkPopover>
  );
}

function StatusMark({
  label,
  notes,
  openSignal,
  editSignal,
}: {
  label?: string;
  notes: readonly FieldNote[];
  openSignal: string | null;
  editSignal: unknown;
}) {
  const t = useTranslate();
  const mode = useContext(FieldDisclosureContext);
  const tone = noteTone(notes) as FieldTone;
  const [opened, setOpened] = useState(false);
  const pinned = useRef(false);
  const timer = useRef<number | null>(null);
  const signalSeen = useRef<string | null>(null);
  const hadNotes = useRef(false);
  const editSeen = useRef(editSignal);

  const clearTimer = () => {
    if (timer.current == null) return;
    window.clearTimeout(timer.current);
    timer.current = null;
  };
  useEffect(() => () => clearTimer(), []);

  useEffect(() => {
    if (!openSignal || openSignal === signalSeen.current) return;
    signalSeen.current = openSignal;
    pinned.current = true;
    setOpened(true);
  }, [openSignal]);

  useEffect(() => {
    if (mode !== "open-once") return;
    if (!hadNotes.current) {
      pinned.current = true;
      setOpened(true);
    }
    hadNotes.current = true;
  }, [mode]);

  useEffect(() => {
    if (Object.is(editSeen.current, editSignal)) return;
    editSeen.current = editSignal;
    if (mode !== "open-once") return;
    pinned.current = false;
    setOpened(false);
  }, [editSignal, mode]);

  const enter = () => {
    clearTimer();
    setOpened(true);
  };
  const leave = () => {
    clearTimer();
    timer.current = window.setTimeout(() => {
      timer.current = null;
      if (!pinned.current) setOpened(false);
    }, HOVER_CLOSE_MS);
  };
  const toggle = () => {
    if (opened && pinned.current) {
      pinned.current = false;
      setOpened(false);
      return;
    }
    pinned.current = true;
    setOpened(true);
  };
  const caption = t("form.field.status");
  return (
    <MarkPopover
      opened={opened}
      name={label ? `${label} ${caption}` : caption}
      tone={tone}
      icon="status"
      onEnter={enter}
      onLeave={leave}
      onToggle={toggle}
      onDismiss={() => {
        pinned.current = false;
        setOpened(false);
      }}
    >
      <Stack gap={4}>
        {orderedNotes(notes).map((note, index) => (
          <Text
            key={`${note.tone}-${index}`}
            size="xs"
            c={note.tone === "warning" ? "yellow" : note.tone === "error" ? "red" : "dimmed"}
          >
            {note.text}
          </Text>
        ))}
      </Stack>
    </MarkPopover>
  );
}

function MarkPopover({
  opened,
  name,
  tone,
  icon,
  onEnter,
  onLeave,
  onToggle,
  onDismiss,
  children,
}: {
  opened: boolean;
  name: string;
  tone: FieldTone | "description";
  icon: "info" | "status";
  onEnter: () => void;
  onLeave: () => void;
  onToggle: () => void;
  onDismiss: () => void;
  children: ReactNode;
}) {
  return (
    <Popover
      opened={opened}
      position="bottom-start"
      offset={4}
      withinPortal
      trapFocus={false}
      onChange={(next) => {
        if (!next) onDismiss();
      }}
    >
      <Popover.Target>
        <button
          type="button"
          className="field-mark"
          data-tone={tone}
          aria-label={name}
          aria-expanded={opened}
          onMouseEnter={onEnter}
          onMouseLeave={onLeave}
          onClick={(event) => {
            event.preventDefault();
            event.stopPropagation();
            onToggle();
          }}
        >
          {icon === "info" ? <InfoIcon size={14} /> : <StatusDotIcon size={14} />}
        </button>
      </Popover.Target>
      <Popover.Dropdown onMouseEnter={onEnter} onMouseLeave={onLeave}>
        {children}
      </Popover.Dropdown>
    </Popover>
  );
}

type ChromeProps = {
  label?: ReactNode;
  description?: ReactNode;
  helper?: ReactNode;
  notes: readonly FieldNote[];
  required?: boolean;
  id?: string;
  openSignal?: string | null;
  editSignal?: unknown;
  bare?: boolean;
  children: (control: { id: string; invalid: boolean; describedBy?: string }) => ReactNode;
};

export function FieldChrome({
  label,
  description,
  helper,
  notes,
  required,
  id,
  openSignal = null,
  editSignal,
  bare = false,
  children,
}: ChromeProps) {
  const generated = useId();
  const controlId = id ?? generated;
  const rootRef = useRef<HTMLDivElement>(null);
  const helperText = presentDescription(helper);
  const helperId = helperText != null ? `${controlId}-helper` : undefined;
  // Mantine replaces aria-describedby while rendering the input, so restore the helper id after each commit.
  useLayoutEffect(() => {
    const root = rootRef.current;
    if (!root || !helperId) return;
    const field = root.querySelector<HTMLElement>("input, textarea, select");
    if (!field) return;
    const ids = (field.getAttribute("aria-describedby") ?? "").split(/\s+/).filter(Boolean);
    if (ids.includes(helperId)) return;
    ids.push(helperId);
    field.setAttribute("aria-describedby", ids.join(" "));
  });
  if (bare) return children({ id: controlId, invalid: false });
  const tone = noteTone(notes);
  const invalid = tone === "error";
  const visibleLabel = label != null && label !== "";
  const descriptionText = visibleLabel ? presentDescription(description) : undefined;
  const labelText = typeof label === "string" ? label : undefined;
  const marks = (
    <FieldMarks
      label={labelText}
      description={descriptionText}
      notes={notes}
      openSignal={openSignal}
      editSignal={editSignal}
    />
  );
  const overlay = !visibleLabel && notes.length > 0;
  return (
    <div
      ref={rootRef}
      className="field-chrome"
      data-tone={tone === "warning" ? "warning" : undefined}
    >
      {visibleLabel ? (
        <div className="field-chrome__label">
          <Input.Label htmlFor={controlId} required={required}>
            {label}
          </Input.Label>
          {marks}
        </div>
      ) : null}
      <div className={overlay ? "field-chrome__control" : undefined}>
        {children({ id: controlId, invalid, describedBy: helperId })}
        {overlay ? <div className="field-chrome__overlay">{marks}</div> : null}
      </div>
      {helperText != null ? (
        <Text id={helperId} className="field-chrome__helper" size="xs" c="dimmed" component="div">
          {helperText}
        </Text>
      ) : null}
    </div>
  );
}
