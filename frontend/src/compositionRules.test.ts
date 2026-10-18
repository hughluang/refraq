import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const SRC = import.meta.dirname;

const NOTIFICATIONS = "@mantine/notifications";
const TABLER = "@tabler/icons-react";
const SPOTLIGHT = "@mantine/spotlight";
const NPROGRESS = "@mantine/nprogress";
const NEXT_NAV = "next/navigation";

const NOTIFICATION_FILES = new Set([
  "providers/notification-provider.ts",
  "app/providers.tsx",
]);

const SHELL_FILES = new Set(["app/providers.tsx", "app/console/layout.tsx"]);

/**
 * Feature files that read useSearchParams because useListQuery and
 * useConsoleTab do not cover the read. Each value is the reason.
 * Keep this empty unless a read truly has no hook.
 */
const SEARCH_PARAMS_EXCEPTIONS: Record<string, string> = {};

const COLOR_ALLOW: Record<string, string> = {
  "features/branding/color.ts":
    "Brand contrast math compares literal black and white foregrounds.",
  "features/branding/color.test.ts":
    "Fixtures exercise brand contrast math.",
  "features/branding/theme.test.ts":
    "Shade fixtures exercise the brand palette generator.",
  "features/branding/types.ts":
    "The default brand primary is a stored hex color.",
  "features/branding/types.test.ts":
    "Fixture for the default brand primary.",
  "features/branding/BrandingPanel.tsx":
    "Preset swatches are the Site Branding palette input.",
};

const STATIC_TABLES: Record<string, { roots: number; reason: string }> = {
  "features/sources/catalog-detail/SampleTab.tsx": {
    roots: 1,
    reason: "Catalog Sample is a static peek at source rows, not a paged collection.",
  },
  "features/sources/structure-diffs/StructureDiffDetail.tsx": {
    roots: 2,
    reason: "Structure Diff detail is a static change breakdown, not a paged collection.",
  },
  "features/entities/AttributeEditor.tsx": {
    roots: 1,
    reason: "The attribute editor is an inline definition grid, not a record collection.",
  },
  "features/dictionaries/DictionaryFormFields.tsx": {
    roots: 1,
    reason: "Dictionary entries are edited in place as form fields, not a record collection.",
  },
  "features/account/McpSection.tsx": {
    roots: 1,
    reason: "The MCP tool list is a static display of the fixed tool catalog.",
  },
  "features/entities/AccessPreviewSection.tsx": {
    roots: 2,
    reason: "Access preview is a fixed sample of marks and cells, not a paged collection.",
  },
  "features/entities/EntityVersionsTab.tsx": {
    roots: 1,
    reason: "The version attribute snapshot is a read-only dump of one version's columns.",
  },
};

const COLOR_LITERAL =
  /#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{4}|[0-9a-fA-F]{3})\b|(?:rgba|rgb|hsla|hsl)\(/g;

const TABLE_ROOT = /<Table(?=[\s>/])|createElement\(\s*Table(?![.\w])/g;

const CONFIRM_NAME = ["window", "confirm"].join(".");
const CONFIRM_CALL = new RegExp(`\\b${CONFIRM_NAME.replace(".", "\\.")}\\b`);

type SourceFile = { rel: string; text: string };

type ImportHit = { specifier: string; clause: string; index: number };

function walk(dir: string, prefix = ""): SourceFile[] {
  const out: SourceFile[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const rel = prefix ? `${prefix}/${entry.name}` : entry.name;
    const abs = path.join(dir, entry.name);
    if (entry.isDirectory()) {
      out.push(...walk(abs, rel));
      continue;
    }
    if (!/\.(?:ts|tsx|css)$/.test(entry.name)) continue;
    out.push({ rel, text: readFileSync(abs, "utf8") });
  }
  return out;
}

const files = walk(SRC);

function isTest(rel: string): boolean {
  return /\.test\.tsx?$/.test(rel);
}

function isFeature(rel: string): boolean {
  return rel.startsWith("features/");
}

function lineOf(text: string, index: number): number {
  return text.slice(0, index).split("\n").length;
}

function importsOf(text: string): ImportHit[] {
  const hits: ImportHit[] = [];
  const fromRe =
    /(?:import|export)\s+(?:type\s+)?([\s\S]*?)\sfrom\s+["']([^"']+)["']/g;
  const sideRe = /import\s+["']([^"']+)["']/g;
  const dynRe = /import\s*\(\s*["']([^"']+)["']\s*\)/g;
  for (const match of text.matchAll(fromRe)) {
    hits.push({
      specifier: match[2] ?? "",
      clause: match[1] ?? "",
      index: match.index ?? 0,
    });
  }
  for (const match of text.matchAll(sideRe)) {
    hits.push({ specifier: match[1] ?? "", clause: "", index: match.index ?? 0 });
  }
  for (const match of text.matchAll(dynRe)) {
    hits.push({ specifier: match[1] ?? "", clause: "", index: match.index ?? 0 });
  }
  return hits;
}

function isPackage(specifier: string, name: string): boolean {
  const bare = specifier.split("?")[0] ?? specifier;
  return bare === name || bare.startsWith(`${name}/`);
}

function bindingNames(clause: string): string[] {
  if (/\*\s+as\s+/.test(clause)) {
    return ["useRouter", "usePathname", "useSearchParams"];
  }
  const brace = clause.match(/\{([\s\S]*)\}/);
  if (!brace?.[1]) return [];
  return brace[1]
    .split(",")
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => part.split(/\s+as\s+/)[0]?.trim() ?? "")
    .filter(Boolean);
}

function notificationsAllowed(rel: string): boolean {
  return NOTIFICATION_FILES.has(rel) || rel.startsWith("components/feedback/");
}

function shellAllowed(rel: string): boolean {
  return SHELL_FILES.has(rel) || rel.startsWith("components/layout/");
}

function packageViolations(name: string, allowed: (rel: string) => boolean, rule: string): string[] {
  const violations: string[] = [];
  for (const file of files) {
    if (isTest(file.rel)) continue;
    for (const hit of importsOf(file.text)) {
      if (!isPackage(hit.specifier, name)) continue;
      if (allowed(file.rel)) continue;
      violations.push(`frontend/src/${file.rel}:${lineOf(file.text, hit.index)}: ${rule}`);
    }
  }
  return violations;
}

function colorHits(text: string): number[] {
  const re = new RegExp(COLOR_LITERAL.source, "g");
  return [...text.matchAll(re)].map((match) => match.index ?? 0);
}

function tableHits(text: string): number[] {
  const re = new RegExp(TABLE_ROOT.source, "g");
  return [...text.matchAll(re)].map((match) => match.index ?? 0);
}

describe("composition rules", () => {
  it("keeps @mantine/notifications inside the feedback layer", () => {
    const violations = packageViolations(
      NOTIFICATIONS,
      notificationsAllowed,
      `${NOTIFICATIONS} is outside the feedback layer`,
    );
    expect(violations, violations.join("\n")).toEqual([]);
  });

  it("keeps @tabler/icons-react inside the icon module", () => {
    const violations = packageViolations(
      TABLER,
      (rel) => rel === "components/icons.tsx",
      `${TABLER} is outside the icon module`,
    );
    expect(violations, violations.join("\n")).toEqual([]);
  });

  it("keeps spotlight and route progress inside the shell", () => {
    const violations = [
      ...packageViolations(
        SPOTLIGHT,
        shellAllowed,
        `${SPOTLIGHT} is outside the shell`,
      ),
      ...packageViolations(
        NPROGRESS,
        shellAllowed,
        `${NPROGRESS} is outside the shell`,
      ),
    ];
    expect(violations, violations.join("\n")).toEqual([]);
  });

  it("keeps Next router hooks out of features", () => {
    const violations: string[] = [];
    for (const file of files) {
      if (!isFeature(file.rel) || isTest(file.rel)) continue;
      for (const hit of importsOf(file.text)) {
        if (!isPackage(hit.specifier, NEXT_NAV)) continue;
        for (const name of bindingNames(hit.clause)) {
          if (name !== "useRouter" && name !== "usePathname") continue;
          violations.push(
            `frontend/src/${file.rel}:${lineOf(file.text, hit.index)}: ${NEXT_NAV} ${name} is forbidden in features; use the console navigation hook`,
          );
        }
      }
    }
    expect(violations, violations.join("\n")).toEqual([]);
  });

  it("allows useSearchParams in features only with an explicit reason", () => {
    const violations: string[] = [];
    const seen = new Set<string>();
    for (const [rel, reason] of Object.entries(SEARCH_PARAMS_EXCEPTIONS)) {
      if (!reason.trim()) {
        violations.push(
          `frontend/src/${rel}: ${NEXT_NAV} useSearchParams exception needs a reason`,
        );
      }
      const file = files.find((item) => item.rel === rel);
      if (!file) {
        violations.push(
          `frontend/src/${rel}: ${NEXT_NAV} useSearchParams exception file is missing`,
        );
        continue;
      }
      const imported = importsOf(file.text).some(
        (hit) =>
          isPackage(hit.specifier, NEXT_NAV) &&
          bindingNames(hit.clause).includes("useSearchParams"),
      );
      if (!imported) {
        violations.push(
          `frontend/src/${rel}: ${NEXT_NAV} useSearchParams exception is stale`,
        );
      }
    }
    for (const file of files) {
      if (!isFeature(file.rel) || isTest(file.rel)) continue;
      for (const hit of importsOf(file.text)) {
        if (!isPackage(hit.specifier, NEXT_NAV)) continue;
        if (!bindingNames(hit.clause).includes("useSearchParams")) continue;
        seen.add(file.rel);
        if (file.rel in SEARCH_PARAMS_EXCEPTIONS) continue;
        violations.push(
          `frontend/src/${file.rel}:${lineOf(file.text, hit.index)}: ${NEXT_NAV} useSearchParams is forbidden in features; list and tab hooks cover the read, or add a reason to SEARCH_PARAMS_EXCEPTIONS`,
        );
      }
    }
    expect(violations, violations.join("\n")).toEqual([]);
    expect(seen.size).toBe(Object.keys(SEARCH_PARAMS_EXCEPTIONS).length);
  });

  it("rejects window confirm", () => {
    const violations: string[] = [];
    for (const file of files) {
      const match = CONFIRM_CALL.exec(file.text);
      CONFIRM_CALL.lastIndex = 0;
      if (!match) continue;
      violations.push(
        `frontend/src/${file.rel}:${lineOf(file.text, match.index)}: ${CONFIRM_NAME} is forbidden`,
      );
    }
    expect(violations, violations.join("\n")).toEqual([]);
  });

  it("rejects color literals in features and CSS", () => {
    const violations: string[] = [];
    const allow = new Set(Object.keys(COLOR_ALLOW));
    for (const [rel, reason] of Object.entries(COLOR_ALLOW)) {
      if (!reason.trim()) {
        violations.push(`frontend/src/${rel}: color literal allowlist needs a reason`);
      }
      const file = files.find((item) => item.rel === rel);
      if (!file) {
        violations.push(`frontend/src/${rel}: color literal allowlist file is missing`);
        continue;
      }
      if (colorHits(file.text).length === 0) {
        violations.push(`frontend/src/${rel}: color literal allowlist entry is stale`);
      }
    }
    for (const file of files) {
      const inScope = file.rel.endsWith(".css") || isFeature(file.rel);
      if (!inScope || allow.has(file.rel)) continue;
      for (const index of colorHits(file.text)) {
        violations.push(
          `frontend/src/${file.rel}:${lineOf(file.text, index)}: color literal is forbidden outside brand color math`,
        );
      }
    }
    expect(violations, violations.join("\n")).toEqual([]);
  });

  it("rejects a raw table root in features outside static display tables", () => {
    const violations: string[] = [];
    for (const [rel, entry] of Object.entries(STATIC_TABLES)) {
      if (!entry.reason.trim()) {
        violations.push(`frontend/src/${rel}: raw Table allowlist needs a reason`);
      }
      const file = files.find((item) => item.rel === rel);
      if (!file) {
        violations.push(`frontend/src/${rel}: raw Table allowlist file is missing`);
        continue;
      }
      const count = tableHits(file.text).length;
      if (count !== entry.roots) {
        violations.push(
          `frontend/src/${rel}: raw Table root count is ${count}, allowlist expects ${entry.roots} (${entry.reason})`,
        );
      }
    }
    for (const file of files) {
      if (!isFeature(file.rel) || isTest(file.rel)) continue;
      if (file.rel in STATIC_TABLES) continue;
      for (const index of tableHits(file.text)) {
        violations.push(
          `frontend/src/${file.rel}:${lineOf(file.text, index)}: raw Table root is forbidden outside static display tables`,
        );
      }
    }
    expect(violations, violations.join("\n")).toEqual([]);
  });
});
