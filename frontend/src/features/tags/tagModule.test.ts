import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { IconApps, IconTag } from "@tabler/icons-react";
import { describe, expect, it, vi } from "vitest";

import { moduleIcon } from "@/components/icons";
import {
  PALETTE_RECORD_LIMIT,
  PALETTE_RECORD_MODULES,
  searchPaletteRecords,
} from "@/components/layout/paletteRecords";
import { GENERATED_MODULE_CATALOG } from "@/features/console/module-identity/generated-catalog";
import { listTags } from "@/features/tags/api";
import en from "@/locales/en-US/common.json";
import zh from "@/locales/zh-CN/common.json";

vi.mock("@/features/tags/api", () => ({
  listTags: vi.fn(),
}));

const COPY_KEYS = [
  "layout.navGroup.tags",
  "tags.title",
  "tags.description",
  "tags.search",
  "tags.list.empty",
  "tags.list.noMatch",
  "tags.create",
  "tags.create.title",
  "tags.create.submit",
  "tags.create.success",
  "tags.edit.title",
  "tags.edit.submit",
  "tags.update.success",
  "tags.update.failed",
  "tags.delete.success",
  "tags.delete.confirmTitle",
  "tags.delete.consequence",
  "tags.backToList",
  "tags.actions.navigation",
  "tags.actions.standard",
  "tags.fields.name",
  "tags.fields.description",
  "tags.fields.updatedAt",
  "tags.validation.name",
  "problems.TAG_NOT_FOUND",
  "problems.TAG_NAME_INVALID",
  "problems.TAG_NAME_CONFLICT",
  "problems.TAG_DESCRIPTION_INVALID",
] as const;

describe("tag module", () => {
  it("registers the record routes", () => {
    const tags = GENERATED_MODULE_CATALOG.find((module) => module.id === "tags");
    expect(tags?.routes).toEqual({
      list: "/console/tags",
      create: "/console/tags/new",
      edit: "/console/tags/:id/edit",
      show: "/console/tags/:id",
      aliases: [],
    });
    expect(tags?.icon).toBe("tag");
    expect(tags?.label_key).toBe("tags.title");
  });

  it("lists at most five tags for the command palette", async () => {
    expect(PALETTE_RECORD_MODULES).toContain("tags");
    vi.mocked(listTags).mockResolvedValue({
      items: Array.from({ length: 8 }, (_, index) => ({
        id: `tag_${index.toString(16).padStart(12, "0")}`,
        name: `Tag ${index}`,
        description: null,
        created_at: "2026-01-01T00:00:00Z",
        updated_at: "2026-01-01T00:00:00Z",
      })),
      total: 8,
      limit: PALETTE_RECORD_LIMIT,
      offset: 0,
    });
    const tags = GENERATED_MODULE_CATALOG.find((module) => module.id === "tags");
    expect(tags).toBeDefined();
    if (!tags) return;
    const result = await searchPaletteRecords({
      query: "Tag",
      moduleIds: ["tags"],
      identities: [tags],
      signal: new AbortController().signal,
    });
    expect(result.hits).toHaveLength(PALETTE_RECORD_LIMIT);
    expect(result.hits[0]?.href).toBe("/console/tags/tag_000000000000");
    expect(listTags).toHaveBeenCalledWith(
      expect.objectContaining({ q: "Tag", limit: PALETTE_RECORD_LIMIT }),
    );
  });

  it("resolves the tag icon instead of the apps fallback", () => {
    const rendered = renderToStaticMarkup(createElement(moduleIcon("tag")));
    const tag = renderToStaticMarkup(
      createElement(IconTag, { size: 16, stroke: 1.5 }),
    );
    const apps = renderToStaticMarkup(
      createElement(IconApps, { size: 16, stroke: 1.5 }),
    );
    expect(rendered).toBe(tag);
    expect(rendered).not.toBe(apps);
  });

  it("has English and Chinese operator copy", () => {
    const english = en as Record<string, string>;
    const chinese = zh as Record<string, string>;
    for (const key of COPY_KEYS) {
      expect(english[key], key).toEqual(expect.any(String));
      expect(chinese[key], key).toEqual(expect.any(String));
      expect(english[key].length).toBeGreaterThan(0);
      expect(chinese[key].length).toBeGreaterThan(0);
    }
  });
});
