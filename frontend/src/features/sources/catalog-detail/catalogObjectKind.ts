const ROUTINE_OBJECT_TYPES = new Set(["procedure", "function"]);

export function isSampleEligible(objectType: string): boolean {
  return !ROUTINE_OBJECT_TYPES.has(objectType);
}
