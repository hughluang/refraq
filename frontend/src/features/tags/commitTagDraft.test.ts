import { describe, expect, it } from "vitest";

import { commitTagDraft } from "@/features/tags/commitTagDraft";

const ledger = { id: "tag_ledger", name: "Ledger" };

describe("commitTagDraft", () => {
  it("leaves an empty set empty for a blank or whitespace field", () => {
    const selected: { id: string; name: string }[] = [];
    const pending: string[] = [];
    for (const raw of ["", "   "]) {
      const next = commitTagDraft({ raw, selected, pending, matches: [] });
      expect(next.selected).toBe(selected);
      expect(next.pending).toBe(pending);
      expect(next.draft).toEqual({ tag_ids: [], names: [] });
    }
  });

  it("adds a typed name to the write set and keeps the chip arrays", () => {
    const selected = [ledger];
    const pending: string[] = [];
    const next = commitTagDraft({
      raw: "  Books  ",
      selected,
      pending,
      matches: [],
    });
    expect(next.selected).toBe(selected);
    expect(next.pending).toEqual(["Books"]);
    expect(next.draft).toEqual({ tag_ids: ["tag_ledger"], names: ["Books"] });
  });

  it("does not add a second pending name that differs only by case", () => {
    const pending = ["Books"];
    const next = commitTagDraft({
      raw: "books",
      selected: [],
      pending,
      matches: [],
    });
    expect(next.pending).toBe(pending);
    expect(next.draft.names).toEqual(["Books"]);
  });

  it("attaches a vocabulary match by id and skips a name already selected", () => {
    const attached = commitTagDraft({
      raw: "ledger",
      selected: [],
      pending: [],
      matches: [ledger],
    });
    expect(attached.draft).toEqual({ tag_ids: ["tag_ledger"], names: [] });
    expect(attached.selected).toEqual([ledger]);

    const selected = [ledger];
    const again = commitTagDraft({
      raw: "LEDGER",
      selected,
      pending: [],
      matches: [ledger],
    });
    expect(again.selected).toBe(selected);
    expect(again.draft).toEqual({ tag_ids: ["tag_ledger"], names: [] });
  });
});
