type NamedTag = {
  id: string;
  name: string;
};

/** Identity of a stored Tag assignment. A new array with the same pairs is the same assignment. */
export function tagAssignmentKey(tagRevision: number, tags: readonly NamedTag[]): string {
  return JSON.stringify([
    tagRevision,
    tags.map((tag) => [tag.id, tag.name]),
  ]);
}
