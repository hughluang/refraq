type Translate = (key: string) => string;

function labeled(t: Translate, group: string, code: string): string {
  const key = `${group}.${code}`;
  const label = t(key);
  if (label !== key) return label;
  return t(`${group}.unknown`);
}

export function objectTypeLabel(t: Translate, objectType: string): string {
  return labeled(t, "catalog.objectTypes", objectType);
}

export function semanticSourceLabel(t: Translate, source: string): string {
  return labeled(t, "catalog.semanticSources", source);
}
