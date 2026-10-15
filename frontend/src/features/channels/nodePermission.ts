export function canAuthorNodeType(
  permission: string | null | undefined,
  held: unknown,
): boolean {
  if (permission == null || permission === "") return true;
  return Array.isArray(held) && held.includes(permission);
}
