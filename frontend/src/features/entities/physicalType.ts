import { ATTRIBUTE_TYPE_CATALOG } from "@/features/entities/attributeTypes.generated";
import type { AttributeDraft } from "@/features/entities/types";

/**
 * Postgres column type shown for an attribute draft.
 * Fills the physical template from the generated Attribute Type catalog.
 */

function strictInt(value: string): number | null {
  const trimmed = value.trim();
  if (!/^\d+$/.test(trimmed)) return null;
  const parsed = Number(trimmed);
  return Number.isSafeInteger(parsed) ? parsed : null;
}

type SlotName = "max_length" | "precision" | "scale";

function slotText(
  attr: Pick<AttributeDraft, "max_length" | "precision" | "scale">,
  name: SlotName,
): string {
  switch (name) {
    case "max_length":
      return attr.max_length;
    case "precision":
      return attr.precision;
    case "scale":
      return attr.scale;
  }
}

export function physicalColumnType(
  attr: Pick<AttributeDraft, "type" | "max_length" | "precision" | "scale">,
): string {
  const physical = ATTRIBUTE_TYPE_CATALOG[attr.type].physical;
  const names = [...physical.template.matchAll(/\{([a-z_]+)\}/g)].map(
    (match) => match[1],
  );
  if (names.length === 0) return physical.template;
  const filled = new Map<string, string>();
  for (const name of names) {
    const parsed = strictInt(slotText(attr, name as SlotName));
    if (parsed == null) return physical.bare;
    filled.set(name, String(parsed));
  }
  let rendered: string = physical.template;
  for (const [name, value] of filled) {
    rendered = rendered.replace(`{${name}}`, value);
  }
  return rendered;
}
