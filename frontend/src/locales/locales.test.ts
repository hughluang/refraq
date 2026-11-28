import fs from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import en from "@/locales/en-US/common.json";
import zh from "@/locales/zh-CN/common.json";

const SRC_ROOT = path.resolve(__dirname, "..");

type LocaleDict = Record<string, string>;

const enDict = en as LocaleDict;
const zhDict = zh as LocaleDict;

function walkSourceFiles(dir: string, out: string[] = []): string[] {
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      walkSourceFiles(full, out);
    } else if (
      /\.(ts|tsx)$/.test(entry.name) &&
      !/\.(test|spec)\.(ts|tsx)$/.test(entry.name)
    ) {
      out.push(full);
    }
  }
  return out;
}

const CALL_RE = /(?<![.\w])(?:t|translate|translateKey)\(\s*([^(),;{}]+?)\s*(?:,|\))/gs;
const LABEL_ATTR_RE = /labelKey\s*=\s*(?:\{\s*([^}]+?)\s*\}|(["'])([^"']+)\2)/gs;
const LABEL_PROP_RE = /\blabelKey\s*:\s*([^,\n}]+)/g;
const STRING_KEY_RE = /["']([a-zA-Z0-9_-]+(?:\.[a-zA-Z0-9_-]+)+)["']/g;

function lineNumberAt(text: string, index: number): number {
  let line = 1;
  for (let i = 0; i < index; i += 1) {
    if (text.charCodeAt(i) === 10) line += 1;
  }
  return line;
}

function collectReferencedKeys(): { file: string; line: number; key: string }[] {
  const refs: { file: string; line: number; key: string }[] = [];

  for (const file of walkSourceFiles(SRC_ROOT)) {
    const source = fs.readFileSync(file, "utf8");
    const relFile = path.relative(SRC_ROOT, file);

    for (const match of source.matchAll(CALL_RE)) {
      const arg = match[1];
      const baseIndex = match.index ?? 0;
      for (const strMatch of arg.matchAll(STRING_KEY_RE)) {
        refs.push({
          file: relFile,
          line: lineNumberAt(source, baseIndex + (strMatch.index ?? 0)),
          key: strMatch[1],
        });
      }
    }

    for (const match of source.matchAll(LABEL_ATTR_RE)) {
      const baseIndex = match.index ?? 0;
      if (match[3]) {
        refs.push({
          file: relFile,
          line: lineNumberAt(source, baseIndex),
          key: match[3],
        });
      } else if (match[1]) {
        for (const strMatch of match[1].matchAll(STRING_KEY_RE)) {
          refs.push({
            file: relFile,
            line: lineNumberAt(source, baseIndex),
            key: strMatch[1],
          });
        }
      }
    }

    for (const match of source.matchAll(LABEL_PROP_RE)) {
      const baseIndex = match.index ?? 0;
      for (const strMatch of match[1].matchAll(STRING_KEY_RE)) {
        refs.push({
          file: relFile,
          line: lineNumberAt(source, baseIndex),
          key: strMatch[1],
        });
      }
    }
  }

  return refs;
}

describe("locales integrity", () => {
  it("keeps en-US and zh-CN key sets identical with non-empty string values", () => {
    const enKeys = Object.keys(enDict).sort();
    const zhKeys = Object.keys(zhDict).sort();

    expect(enKeys).toEqual(zhKeys);

    const emptyEn = enKeys.filter(
      (key) => typeof enDict[key] !== "string" || enDict[key].trim().length === 0,
    );
    const emptyZh = zhKeys.filter(
      (key) => typeof zhDict[key] !== "string" || zhDict[key].trim().length === 0,
    );

    expect(emptyEn).toEqual([]);
    expect(emptyZh).toEqual([]);
  });

  it("resolves every statically referenced translation key in both locales", () => {
    const refs = collectReferencedKeys();
    expect(refs.length).toBeGreaterThan(0);

    const missing = refs
      .filter(({ key }) => !(key in enDict) || !(key in zhDict))
      .map(({ file, line, key }) => `${file}:${line} -> ${key}`);

    expect(missing).toEqual([]);
  });

  it("includes shared action, status, and copy keys used across Console features", () => {
    const requiredKeys = [
      "actions.done",
      "actions.revoke",
      "common.clear",
      "common.copy.label",
      "common.description",
      "common.no",
      "common.yes",
      "status.disabled",
      "status.enabled",
    ];

    for (const key of requiredKeys) {
      expect(enDict[key]).toBeTruthy();
      expect(zhDict[key]).toBeTruthy();
    }
  });
});
