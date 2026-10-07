export type AccessOption = { value: string; label: string };

/** `savedKey` null reloads nothing and shows no success toast. Failures still notify. */
export type AccessRun = (
  id: string,
  savedKey: string | null,
  work: () => Promise<void>,
) => Promise<boolean>;
