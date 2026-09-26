import type { ComboboxData, ComboboxItem } from "@mantine/core";

function findLabel(data: ComboboxData, value: string): string | undefined {
  for (const item of data) {
    if (typeof item === "string" || typeof item === "number") {
      if (String(item) === value) return String(item);
      continue;
    }
    const option = item as ComboboxItem;
    if (option.value === value) return option.label ?? option.value;
  }
  return undefined;
}

/** Option label for a stored value. Unmatched values stay as the raw value. */
export function optionLabel(data: ComboboxData, value: string): string {
  return findLabel(data, value) ?? value;
}

export function optionLabels(data: ComboboxData, values: readonly string[]): string {
  if (values.length === 0) return "";
  return values.map((value) => optionLabel(data, value)).join(", ");
}
