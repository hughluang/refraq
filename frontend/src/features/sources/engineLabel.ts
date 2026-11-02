import type { Engine } from "@/features/sources/types";

type Translate = (key: string) => string;

export const SOURCE_ENGINES = [
  "postgresql",
  "mssql",
  "oracle",
] as const satisfies readonly Engine[];

export function selectedEngine(value: string): Engine | undefined {
  return SOURCE_ENGINES.find((engine) => engine === value);
}

/** Localized Source engine. An unknown code uses the generic label, not the code. */
export function engineLabel(t: Translate, engine: string): string {
  const key = `sources.engines.${engine}`;
  const label = t(key);
  if (label !== key) return label;
  return t("sources.engines.unknown");
}
