export type MatchKeyAttribute = {
  name: string;
  business_key: boolean;
};

export function resolvedMatchKeyName(
  matchKey: unknown,
  attributes: readonly MatchKeyAttribute[],
): string | null {
  if (matchKey == null || matchKey === "") {
    return attributes.find((attribute) => attribute.business_key)?.name ?? null;
  }
  if (typeof matchKey !== "string") return null;
  return attributes.some((attribute) => attribute.name === matchKey) ? matchKey : null;
}
