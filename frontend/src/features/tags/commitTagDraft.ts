type NamedTag = {
  id: string;
  name: string;
};

export type TagDraft = {
  tag_ids: string[];
  names: string[];
};

type CommitInput<T extends NamedTag> = {
  raw: string;
  selected: readonly T[];
  pending: readonly string[];
  matches: readonly T[];
};

export type CommittedTagDraft<T extends NamedTag> = {
  selected: T[];
  pending: string[];
  draft: TagDraft;
};

/**
 * The set the next Tag write will persist.
 * A blank field leaves the chips unchanged. A typed name joins that set
 * without copying the chip arrays when nothing new is added.
 */
export function commitTagDraft<T extends NamedTag>(
  input: CommitInput<T>,
): CommittedTagDraft<T> {
  const name = input.raw.trim();
  let selected = input.selected;
  let pending = input.pending;
  if (name !== "") {
    const match = input.matches.find(
      (item) => item.name.toLowerCase() === name.toLowerCase(),
    );
    if (match) {
      if (!selected.some((tag) => tag.id === match.id)) {
        selected = [...selected, match];
      }
    } else if (!pending.some((item) => item.toLowerCase() === name.toLowerCase())) {
      pending = [...pending, name];
    }
  }
  return {
    selected: selected as T[],
    pending: pending as string[],
    draft: {
      tag_ids: selected.map((tag) => tag.id),
      names: [...pending],
    },
  };
}
