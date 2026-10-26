import type { Tag, TagFormValues } from "@/features/tags/types";

export const EMPTY_TAG_FORM: TagFormValues = {
  name: "",
  description: "",
};

type Translate = (key: string) => string;

export function tagFormErrors(
  values: TagFormValues,
  t: Translate,
): Record<string, string> {
  if (values.name.trim().length === 0) {
    return { name: t("tags.validation.name") };
  }
  return {};
}

export function formFromTag(tag: Tag): TagFormValues {
  return {
    name: tag.name,
    description: tag.description ?? "",
  };
}
