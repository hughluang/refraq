"use client";

import {
  Button,
  Combobox,
  Group,
  Input,
  InputBase,
  Pill,
  PillsInput,
  Stack,
  Text,
  useCombobox,
  type BoxProps,
  type MantineStyleProp,
} from "@mantine/core";
import { useTranslate } from "@refinedev/core";
import {
  useEffect,
  useRef,
  useState,
  type FocusEventHandler,
  type ReactNode,
} from "react";

import { FieldChrome } from "@/components/form/FieldChrome";
import { FieldMode } from "@/components/form/FieldMode";
import { CheckIcon } from "@/components/icons";
import {
  collectNotes,
  joinDescribedBy,
  type FieldChromeProps,
} from "@/components/form/fieldNotes";
import {
  isAbortError,
  type RecordOption,
  type RecordPickerAdapter,
} from "@/components/form/recordPickerAdapters";

export type { RecordOption, RecordPickerAdapter } from "@/components/form/recordPickerAdapters";

export const RECORD_PICKER_DEBOUNCE_MS = 250;

type SearchStatus = "idle" | "searching" | "ready" | "error";

type FormPassthrough = {
  defaultValue?: unknown;
  checked?: unknown;
  defaultChecked?: unknown;
};

type Chrome = FieldChromeProps & {
  adapter: RecordPickerAdapter;
  editable: boolean;
  label?: ReactNode;
  description?: ReactNode;
  required?: boolean;
  error?: ReactNode;
  disabled?: boolean;
  clearable?: boolean;
  excludeIds?: readonly string[];
  placeholder?: string;
  id?: string;
  w?: BoxProps["w"];
  style?: MantineStyleProp;
  known?: readonly RecordOption[];
  onBlur?: FocusEventHandler<HTMLButtonElement | HTMLInputElement>;
  onFocus?: FocusEventHandler<HTMLButtonElement | HTMLInputElement>;
};

export type RecordPickerProps = Chrome &
  FormPassthrough & {
    value?: string | null;
    onChange?: (value: string | null, option: RecordOption | null) => void;
  };

export type RecordMultiPickerProps = Chrome &
  FormPassthrough & {
    value?: readonly string[];
    onChange?: (value: string[]) => void;
  };

function useResolved(
  adapter: RecordPickerAdapter,
  ids: readonly string[],
  known: readonly RecordOption[] | undefined,
) {
  const cache = useRef(new Map<string, RecordOption>());
  const [, bump] = useState(0);
  for (const option of known ?? []) {
    if (option.id) cache.current.set(option.id, option);
  }
  const key = ids.filter((id) => id !== "").join("\0");
  useEffect(() => {
    const missing = (key === "" ? [] : key.split("\0")).filter((id) => !cache.current.has(id));
    if (missing.length === 0) return;
    const controller = new AbortController();
    let cancelled = false;
    void adapter
      .resolve(missing, controller.signal)
      .then((found) => {
        if (cancelled) return;
        for (const option of found) cache.current.set(option.id, option);
        for (const id of missing) {
          if (!cache.current.has(id)) cache.current.set(id, { id, name: id, key: id });
        }
        bump((value) => value + 1);
      })
      .catch((error: unknown) => {
        if (cancelled || isAbortError(error)) return;
        for (const id of missing) {
          if (!cache.current.has(id)) cache.current.set(id, { id, name: id, key: id });
        }
        bump((value) => value + 1);
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [adapter, key]);

  return {
    get(id: string) {
      return cache.current.get(id);
    },
    remember(option: RecordOption) {
      cache.current.set(option.id, option);
      bump((value) => value + 1);
    },
  };
}

function useRecordSearch(
  adapter: RecordPickerAdapter,
  query: string,
  active: boolean,
  retryNonce: number,
) {
  const [options, setOptions] = useState<RecordOption[]>([]);
  const [status, setStatus] = useState<SearchStatus>("idle");
  const optionsRef = useRef(options);
  optionsRef.current = options;
  const seqRef = useRef(0);

  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    const seq = ++seqRef.current;
    const delay = query.trim() === "" ? 0 : RECORD_PICKER_DEBOUNCE_MS;
    setStatus("searching");
    const timer = window.setTimeout(() => {
      void adapter.search(query.trim(), controller.signal).then(
        (items) => {
          if (seq !== seqRef.current || controller.signal.aborted) return;
          setOptions(items);
          setStatus("ready");
        },
        (error: unknown) => {
          if (seq !== seqRef.current || controller.signal.aborted || isAbortError(error)) return;
          setOptions([]);
          setStatus("error");
        },
      );
    }, delay);
    return () => {
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [active, adapter, query, retryNonce]);

  return { options, optionsRef, status };
}

function OptionLabel({ option }: { option: RecordOption }) {
  return (
    <Group gap={6} wrap="nowrap" align="baseline">
      <Text size="sm" component="span">
        {option.name}
      </Text>
      <Text size="xs" c="dimmed" ff="monospace" component="span">
        {option.key}
      </Text>
    </Group>
  );
}

function SearchState({
  status,
  count,
  onRetry,
}: {
  status: SearchStatus;
  count: number;
  onRetry: () => void;
}) {
  const t = useTranslate();
  if (status === "searching" || status === "idle") {
    return <Combobox.Empty>{t("recordPicker.searching")}</Combobox.Empty>;
  }
  if (status === "error") {
    return (
      <Combobox.Empty>
        <Stack gap={6} align="flex-start">
          <Text size="sm">{t("common.error.loadFailed")}</Text>
          <Button
            type="button"
            size="xs"
            variant="light"
            onMouseDown={(event) => event.preventDefault()}
            onClick={onRetry}
          >
            {t("common.retry")}
          </Button>
        </Stack>
      </Combobox.Empty>
    );
  }
  if (count === 0) {
    return <Combobox.Empty>{t("recordPicker.empty")}</Combobox.Empty>;
  }
  return null;
}

function visibleOptions(options: readonly RecordOption[], excludeIds: readonly string[] | undefined) {
  if (!excludeIds || excludeIds.length === 0) return options;
  const excluded = new Set(excludeIds);
  return options.filter((option) => !excluded.has(option.id));
}

type Resolved = ReturnType<typeof useResolved>;

function optionOf(id: string, resolved: Resolved, options: readonly RecordOption[]) {
  return options.find((option) => option.id === id) ?? resolved.get(id) ?? null;
}

export function RecordPicker({
  adapter,
  editable,
  label,
  description,
  helper,
  notes,
  openSignal,
  bare = false,
  required,
  error,
  disabled = false,
  clearable = false,
  excludeIds,
  placeholder,
  value,
  onChange,
  onBlur,
  onFocus,
  known,
  w,
  style,
  id,
}: RecordPickerProps) {
  const selectedId = value != null && value !== "" ? value : null;
  const resolved = useResolved(adapter, selectedId ? [selectedId] : [], known);
  const selected = selectedId ? resolved.get(selectedId) : undefined;
  const merged = bare ? [] : collectNotes(error, notes);
  const display = selected ? (
    <OptionLabel option={selected} />
  ) : selectedId ? (
    selectedId
  ) : undefined;
  return (
    <FieldMode
      editable={editable}
      label={label}
      description={bare ? undefined : description}
      notes={merged}
      openSignal={openSignal}
      value={display}
      style={style}
      w={w}
    >
      <FieldChrome
        label={label}
        description={description}
        helper={helper}
        notes={merged}
        required={required}
        id={id}
        openSignal={openSignal}
        editSignal={value}
        bare={bare}
      >
        {({ id: controlId, invalid, describedBy }) => (
          <SingleControl
            id={controlId}
            invalid={invalid}
            describedBy={describedBy}
            adapter={adapter}
            disabled={disabled}
            clearable={clearable}
            excludeIds={excludeIds}
            placeholder={placeholder}
            selectedId={selectedId}
            selected={selected}
            resolved={resolved}
            onChange={onChange}
            onBlur={onBlur}
            onFocus={onFocus}
          />
        )}
      </FieldChrome>
    </FieldMode>
  );
}

function SingleControl({
  id,
  invalid,
  describedBy,
  adapter,
  disabled,
  clearable,
  excludeIds,
  placeholder,
  selectedId,
  selected,
  resolved,
  onChange,
  onBlur,
  onFocus,
}: {
  id: string;
  invalid: boolean;
  describedBy?: string;
  adapter: RecordPickerAdapter;
  disabled: boolean;
  clearable: boolean;
  excludeIds?: readonly string[];
  placeholder?: string;
  selectedId: string | null;
  selected: RecordOption | undefined;
  resolved: Resolved;
  onChange?: (value: string | null, option: RecordOption | null) => void;
  onBlur?: FocusEventHandler<HTMLButtonElement | HTMLInputElement>;
  onFocus?: FocusEventHandler<HTMLButtonElement | HTMLInputElement>;
}) {
  const t = useTranslate();
  const [search, setSearch] = useState("");
  const [active, setActive] = useState(false);
  const [retryNonce, setRetryNonce] = useState(0);
  const combobox = useCombobox({
    onDropdownOpen: () => {
      setActive(true);
      combobox.selectFirstOption();
    },
    onDropdownClose: () => {
      setActive(false);
      setSearch("");
      combobox.resetSelectedOption();
    },
  });
  const { options, optionsRef, status } = useRecordSearch(adapter, search, active, retryNonce);
  const shown = visibleOptions(options, excludeIds);
  const showClear = clearable && selectedId != null && !disabled;
  const prompt = placeholder ?? t("recordPicker.placeholder");

  return (
    <Combobox
      store={combobox}
      withinPortal
      onOptionSubmit={(next) => {
        const option = optionOf(next, resolved, optionsRef.current);
        if (option) resolved.remember(option);
        onChange?.(next, option);
        combobox.closeDropdown();
      }}
    >
      <Combobox.Target targetType="button">
        <InputBase
          id={id}
          component="button"
          type="button"
          pointer
          disabled={disabled}
          error={invalid || undefined}
          aria-describedby={describedBy}
          rightSection={
            showClear ? (
              <Combobox.ClearButton
                onClear={() => {
                  onChange?.(null, null);
                  setSearch("");
                }}
              />
            ) : (
              <Combobox.Chevron />
            )
          }
          rightSectionPointerEvents={showClear ? "all" : "none"}
          onClick={() => {
            if (!disabled) combobox.toggleDropdown();
          }}
          onFocus={onFocus}
          onBlur={onBlur}
        >
          {selected ? (
            <OptionLabel option={selected} />
          ) : (
            <Input.Placeholder>{prompt}</Input.Placeholder>
          )}
        </InputBase>
      </Combobox.Target>
      <Combobox.Dropdown>
        <Combobox.Search
          value={search}
          placeholder={prompt}
          aria-label={prompt}
          onChange={(event) => {
            setSearch(event.currentTarget.value);
            combobox.updateSelectedOptionIndex();
          }}
        />
        <Combobox.Options>
          <SearchState
            status={status}
            count={shown.length}
            onRetry={() => setRetryNonce((value) => value + 1)}
          />
          {status === "ready"
            ? shown.map((option) => (
                <Combobox.Option value={option.id} key={option.id} active={option.id === selectedId}>
                  <OptionLabel option={option} />
                </Combobox.Option>
              ))
            : null}
        </Combobox.Options>
      </Combobox.Dropdown>
    </Combobox>
  );
}

export function RecordMultiPicker({
  adapter,
  editable,
  label,
  description,
  helper,
  notes,
  openSignal,
  bare = false,
  required,
  error,
  disabled = false,
  clearable = false,
  excludeIds,
  placeholder,
  value,
  onChange,
  onBlur,
  onFocus,
  known,
  w,
  style,
  id,
}: RecordMultiPickerProps) {
  const ids = (value ?? []).filter((item) => item !== "");
  const resolved = useResolved(adapter, ids, known);
  const merged = bare ? [] : collectNotes(error, notes);
  const display =
    ids.length === 0 ? undefined : (
      <Stack gap={4}>
        {ids.map((item) => {
          const option = resolved.get(item) ?? { id: item, name: item, key: item };
          return <OptionLabel key={item} option={option} />;
        })}
      </Stack>
    );
  return (
    <FieldMode
      editable={editable}
      label={label}
      description={bare ? undefined : description}
      notes={merged}
      openSignal={openSignal}
      value={display}
      style={style}
      w={w}
    >
      <FieldChrome
        label={label}
        description={description}
        helper={helper}
        notes={merged}
        required={required}
        id={id}
        openSignal={openSignal}
        editSignal={value}
        bare={bare}
      >
        {({ id: controlId, invalid, describedBy }) => (
          <MultiControl
            id={controlId}
            invalid={invalid}
            describedBy={describedBy}
            adapter={adapter}
            disabled={disabled}
            clearable={clearable}
            excludeIds={excludeIds}
            placeholder={placeholder}
            ids={ids}
            resolved={resolved}
            onChange={onChange}
            onBlur={onBlur}
            onFocus={onFocus}
          />
        )}
      </FieldChrome>
    </FieldMode>
  );
}

function MultiControl({
  id,
  invalid,
  describedBy,
  adapter,
  disabled,
  clearable,
  excludeIds,
  placeholder,
  ids,
  resolved,
  onChange,
  onBlur,
  onFocus,
}: {
  id: string;
  invalid: boolean;
  describedBy?: string;
  adapter: RecordPickerAdapter;
  disabled: boolean;
  clearable: boolean;
  excludeIds?: readonly string[];
  placeholder?: string;
  ids: readonly string[];
  resolved: Resolved;
  onChange?: (value: string[]) => void;
  onBlur?: FocusEventHandler<HTMLButtonElement | HTMLInputElement>;
  onFocus?: FocusEventHandler<HTMLButtonElement | HTMLInputElement>;
}) {
  const t = useTranslate();
  const [search, setSearch] = useState("");
  const [active, setActive] = useState(false);
  const [retryNonce, setRetryNonce] = useState(0);
  const combobox = useCombobox({
    onDropdownOpen: () => {
      setActive(true);
      combobox.selectFirstOption();
    },
    onDropdownClose: () => {
      setActive(false);
      setSearch("");
      combobox.resetSelectedOption();
    },
  });
  const { options, optionsRef, status } = useRecordSearch(adapter, search, active, retryNonce);
  const shown = visibleOptions(options, excludeIds);
  const prompt = placeholder ?? t("recordPicker.placeholder");
  const showClear = clearable && ids.length > 0 && !disabled;

  function toggle(next: string) {
    const option = optionOf(next, resolved, optionsRef.current);
    if (option) resolved.remember(option);
    const current = [...ids];
    onChange?.(
      current.includes(next) ? current.filter((item) => item !== next) : [...current, next],
    );
  }

  return (
    <Combobox store={combobox} withinPortal onOptionSubmit={toggle}>
      <Combobox.DropdownTarget>
        <PillsInput
          id={id}
          disabled={disabled}
          error={invalid || undefined}
          pointer
          onClick={() => {
            if (!disabled) combobox.openDropdown();
          }}
          rightSection={
            showClear ? (
              <Combobox.ClearButton
                onClear={() => {
                  onChange?.([]);
                  setSearch("");
                }}
              />
            ) : (
              <Combobox.Chevron />
            )
          }
          rightSectionPointerEvents={showClear ? "all" : "none"}
        >
          <Pill.Group>
            {ids.map((item) => {
              const option = resolved.get(item) ?? { id: item, name: item, key: item };
              return (
                <Pill
                  key={item}
                  withRemoveButton={!disabled}
                  onRemove={() => onChange?.(ids.filter((current) => current !== item))}
                  removeButtonProps={{
                    "aria-label": `${t("recordPicker.remove")} ${option.name}`,
                    "aria-hidden": false,
                  }}
                >
                  <Group gap={6} wrap="nowrap">
                    <span>{option.name}</span>
                    <Text span size="xs" c="dimmed" ff="monospace">
                      {option.key}
                    </Text>
                  </Group>
                </Pill>
              );
            })}
            <Combobox.EventsTarget>
              <PillsInput.Field
                id={id}
                disabled={disabled}
                value={search}
                placeholder={ids.length === 0 ? prompt : undefined}
                aria-describedby={joinDescribedBy(describedBy)}
                onFocus={(event) => {
                  onFocus?.(event);
                  if (!disabled) combobox.openDropdown();
                }}
                onBlur={(event) => {
                  onBlur?.(event);
                  combobox.closeDropdown();
                }}
                onChange={(event) => {
                  setSearch(event.currentTarget.value);
                  combobox.openDropdown();
                  combobox.updateSelectedOptionIndex();
                }}
                onKeyDown={(event) => {
                  if (event.key === "Backspace" && search.length === 0 && ids.length > 0) {
                    event.preventDefault();
                    onChange?.(ids.slice(0, -1));
                  }
                }}
              />
            </Combobox.EventsTarget>
          </Pill.Group>
        </PillsInput>
      </Combobox.DropdownTarget>
      <Combobox.Dropdown>
        <Combobox.Options>
          <SearchState
            status={status}
            count={shown.length}
            onRetry={() => setRetryNonce((value) => value + 1)}
          />
          {status === "ready"
            ? shown.map((option) => (
                <Combobox.Option
                  value={option.id}
                  key={option.id}
                  active={ids.includes(option.id)}
                >
                  <Group gap="sm" wrap="nowrap">
                    {ids.includes(option.id) ? <CheckIcon size={12} /> : null}
                    <OptionLabel option={option} />
                  </Group>
                </Combobox.Option>
              ))
            : null}
        </Combobox.Options>
      </Combobox.Dropdown>
    </Combobox>
  );
}
