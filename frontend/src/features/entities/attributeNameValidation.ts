/** Attribute name rules mirror backend/entity/validate.py (physical column). */

export const ATTRIBUTE_NAME_MAX_LEN = 63;
export const ATTRIBUTE_NAME_RE = /^[a-z][a-z0-9_]*$/;
export const RESERVED_ATTRIBUTE_NAME = "row_id";

export type AttributeNameErrorReason =
  | "required"
  | "charset"
  | "tooLong"
  | "reserved"
  | "duplicate";

/** Null when the trimmed name is a legal attribute name. `siblingNames` includes this name. */
export function attributeNameError(
  name: string,
  siblingNames: readonly string[],
): AttributeNameErrorReason | null {
  const cleaned = name.trim();
  if (!cleaned) {
    return "required";
  }
  if (cleaned.length > ATTRIBUTE_NAME_MAX_LEN) {
    return "tooLong";
  }
  if (!ATTRIBUTE_NAME_RE.test(cleaned)) {
    return "charset";
  }
  if (cleaned === RESERVED_ATTRIBUTE_NAME) {
    return "reserved";
  }
  const matches = siblingNames.filter((item) => item.trim() === cleaned).length;
  if (matches > 1) {
    return "duplicate";
  }
  return null;
}
