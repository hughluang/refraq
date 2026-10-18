type Translate = (key: string) => string;

/** Localized Source engine. An unknown code uses the generic label, not the code. */
export function engineLabel(t: Translate, engine: string): string {
  const key = `sources.engines.${engine}`;
  const label = t(key);
  if (label !== key) return label;
  return t("sources.engines.unknown");
}
