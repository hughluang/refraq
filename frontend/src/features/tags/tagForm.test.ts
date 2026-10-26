import { describe, expect, it } from "vitest";

import { tagFormErrors } from "@/features/tags/tagForm";

const t = (key: string) => key;

describe("tagFormErrors", () => {
  it("rejects an empty name and leaves every other name to the server", () => {
    expect(tagFormErrors({ name: "   ", description: "" }, t)).toEqual({
      name: "tags.validation.name",
    });
    expect(
      tagFormErrors(
        { name: "\u8d22\u52a1-A 😀", description: "a".repeat(300) },
        t,
      ),
    ).toEqual({});
    expect(
      tagFormErrors({ name: "a".repeat(300), description: "" }, t),
    ).toEqual({});
  });
});
