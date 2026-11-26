"use client";

import {
  ActionIcon,
  Box,
  Button,
  Group,
  Stack,
  Switch,
  Text,
  TextInput,
} from "@mantine/core";
import { useNotification, useTranslate } from "@refinedev/core";
import { Fragment, useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { EmptyState } from "@/components/feedback/EmptyState";
import {
  ChevronDownIcon,
  ChevronUpIcon,
  CloseIcon,
  CodeIcon,
  CopyIcon,
  SearchIcon,
} from "@/components/icons";
import { isSampleEligible } from "@/features/sources/catalog-detail/catalogObjectKind";
import { copyText } from "@/lib/copy-text";

type DdlTabProps = {
  ddl: string | null;
  objectType?: string;
  objectName?: string;
};

type SqlTokenKind = "plain" | "keyword" | "string" | "number" | "comment";

type SqlToken = {
  kind: SqlTokenKind;
  text: string;
};

const SQL_KEYWORDS = new Set([
  "ADD",
  "ALL",
  "ALTER",
  "AND",
  "AS",
  "ASC",
  "BEGIN",
  "BETWEEN",
  "BIGINT",
  "BIGSERIAL",
  "BOOLEAN",
  "BY",
  "CASCADE",
  "CASE",
  "CAST",
  "CHAR",
  "CHARACTER",
  "CHECK",
  "COLUMN",
  "COMMENT",
  "CONFLICT",
  "CONSTRAINT",
  "CREATE",
  "CROSS",
  "CURRENT_TIMESTAMP",
  "DATABASE",
  "DATE",
  "DECIMAL",
  "DECLARE",
  "DEFAULT",
  "DELETE",
  "DESC",
  "DISTINCT",
  "DO",
  "DOUBLE",
  "DROP",
  "ELSE",
  "END",
  "EXISTS",
  "FALSE",
  "FLOAT",
  "FOR",
  "FOREIGN",
  "FROM",
  "FULL",
  "FUNCTION",
  "GRANT",
  "GROUP",
  "HAVING",
  "IF",
  "ILIKE",
  "IN",
  "INDEX",
  "INNER",
  "INSERT",
  "INT",
  "INTEGER",
  "INTO",
  "IS",
  "JOIN",
  "JSON",
  "JSONB",
  "KEY",
  "LANGUAGE",
  "LEFT",
  "LIKE",
  "LIMIT",
  "NOT",
  "NOTHING",
  "NULL",
  "NUMERIC",
  "OFFSET",
  "ON",
  "OR",
  "ORDER",
  "OUTER",
  "PRIMARY",
  "PROCEDURE",
  "REAL",
  "REFERENCES",
  "REPLACE",
  "RESTRICT",
  "RETURN",
  "RETURNING",
  "RETURNS",
  "RIGHT",
  "SCHEMA",
  "SELECT",
  "SERIAL",
  "SET",
  "SMALLINT",
  "TABLE",
  "TEXT",
  "THEN",
  "TIME",
  "TIMESTAMP",
  "TIMESTAMPTZ",
  "TO",
  "TRIGGER",
  "TRUE",
  "UNION",
  "UNIQUE",
  "UPDATE",
  "UUID",
  "VALUES",
  "VARCHAR",
  "VARYING",
  "VIEW",
  "WHEN",
  "WHERE",
  "WITH",
]);

function formatByteSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function tokenizeSqlLines(ddl: string): SqlToken[][] {
  const rawLines = ddl.split(/\r?\n/);
  const result: SqlToken[][] = [];
  let inBlockComment = false;

  for (const line of rawLines) {
    const tokens: SqlToken[] = [];
    let i = 0;

    while (i < line.length) {
      if (inBlockComment) {
        const end = line.indexOf("*/", i);
        if (end === -1) {
          tokens.push({ kind: "comment", text: line.slice(i) });
          i = line.length;
        } else {
          tokens.push({ kind: "comment", text: line.slice(i, end + 2) });
          i = end + 2;
          inBlockComment = false;
        }
        continue;
      }

      if (line[i] === "-" && line[i + 1] === "-") {
        tokens.push({ kind: "comment", text: line.slice(i) });
        break;
      }

      if (line[i] === "/" && line[i + 1] === "*") {
        const end = line.indexOf("*/", i + 2);
        if (end === -1) {
          tokens.push({ kind: "comment", text: line.slice(i) });
          inBlockComment = true;
          break;
        }
        tokens.push({ kind: "comment", text: line.slice(i, end + 2) });
        i = end + 2;
        continue;
      }

      if (line[i] === "'") {
        let j = i + 1;
        while (j < line.length) {
          if (line[j] === "'") {
            if (line[j + 1] === "'") {
              j += 2;
              continue;
            }
            j += 1;
            break;
          }
          j += 1;
        }
        tokens.push({ kind: "string", text: line.slice(i, j) });
        i = j;
        continue;
      }

      if (/[0-9]/.test(line[i]) && (i === 0 || !/[A-Za-z0-9_$]/.test(line[i - 1]))) {
        const match = /^[0-9]+(?:\.[0-9]+)?/.exec(line.slice(i));
        if (match) {
          tokens.push({ kind: "number", text: match[0] });
          i += match[0].length;
          continue;
        }
      }

      if (/[A-Za-z_]/.test(line[i])) {
        const match = /^[A-Za-z_][A-Za-z0-9_$]*/.exec(line.slice(i));
        if (match) {
          const word = match[0];
          const kind: SqlTokenKind = SQL_KEYWORDS.has(word.toUpperCase()) ? "keyword" : "plain";
          tokens.push({ kind, text: word });
          i += word.length;
          continue;
        }
      }

      const nextSpecial = line.slice(i + 1).search(/[-/'0-9A-Za-z_]/);
      if (nextSpecial === -1) {
        tokens.push({ kind: "plain", text: line.slice(i) });
        break;
      }
      tokens.push({ kind: "plain", text: line.slice(i, i + 1 + nextSpecial) });
      i += 1 + nextSpecial;
    }

    result.push(tokens);
  }

  return result;
}

function tokenStyle(kind: SqlTokenKind): React.CSSProperties | undefined {
  switch (kind) {
    case "keyword":
      return { color: "var(--mantine-color-blue-text)", fontWeight: 600 };
    case "string":
      return { color: "var(--mantine-color-teal-text)" };
    case "number":
      return { color: "var(--mantine-color-orange-text)" };
    case "comment":
      return { color: "var(--mantine-color-dimmed)", fontStyle: "italic" };
    default:
      return undefined;
  }
}

type SearchMatch = {
  lineIndex: number;
  start: number;
  end: number;
};

function findLineMatches(lines: string[], query: string): SearchMatch[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [];
  const matches: SearchMatch[] = [];
  for (let lineIndex = 0; lineIndex < lines.length; lineIndex += 1) {
    const haystack = lines[lineIndex].toLowerCase();
    let pos = 0;
    while (pos <= haystack.length - needle.length) {
      const idx = haystack.indexOf(needle, pos);
      if (idx === -1) break;
      matches.push({ lineIndex, start: idx, end: idx + needle.length });
      pos = idx + needle.length;
    }
  }
  return matches;
}

function renderTokensWithSearch(
  tokens: SqlToken[],
  lineMatches: Array<{ matchIndex: number; start: number; end: number }>,
  activeMatchIndex: number,
  markRefs: React.MutableRefObject<Map<number, HTMLElement>>,
): ReactNode {
  if (tokens.length === 0) return "\u00A0";
  if (lineMatches.length === 0) {
    return tokens.map((token, idx) =>
      token.kind === "plain" ? (
        <Fragment key={idx}>{token.text}</Fragment>
      ) : (
        <span key={idx} style={tokenStyle(token.kind)}>
          {token.text}
        </span>
      ),
    );
  }

  const nodes: ReactNode[] = [];
  let charOffset = 0;
  let mIdx = 0;

  for (let tIdx = 0; tIdx < tokens.length; tIdx += 1) {
    const token = tokens[tIdx];
    const tokenStart = charOffset;
    const tokenEnd = tokenStart + token.text.length;
    const style = tokenStyle(token.kind);

    let cursor = tokenStart;
    while (mIdx < lineMatches.length && lineMatches[mIdx].end <= tokenStart) {
      mIdx += 1;
    }

    let localMatchIdx = mIdx;
    while (localMatchIdx < lineMatches.length && lineMatches[localMatchIdx].start < tokenEnd) {
      const m = lineMatches[localMatchIdx];
      if (m.start > cursor) {
        const slice = token.text.slice(cursor - tokenStart, m.start - tokenStart);
        nodes.push(
          style ? (
            <span key={`${tIdx}:pre:${cursor}`} style={style}>
              {slice}
            </span>
          ) : (
            <Fragment key={`${tIdx}:pre:${cursor}`}>{slice}</Fragment>
          ),
        );
      }

      const overlapStart = Math.max(cursor, m.start);
      const overlapEnd = Math.min(tokenEnd, m.end);
      const matchSlice = token.text.slice(overlapStart - tokenStart, overlapEnd - tokenStart);
      const isActive = m.matchIndex === activeMatchIndex;
      const isFirstSegment = overlapStart === m.start;

      nodes.push(
        <mark
          key={`${tIdx}:mark:${m.matchIndex}:${overlapStart}`}
          ref={
            isFirstSegment
              ? (el) => {
                  if (el) markRefs.current.set(m.matchIndex, el);
                  else markRefs.current.delete(m.matchIndex);
                }
              : undefined
          }
          data-active-match={isActive ? "true" : undefined}
          style={{
            backgroundColor: "var(--mantine-color-yellow-light)",
            color: "inherit",
            borderRadius: "2px",
            outline: isActive ? "2px solid var(--mantine-color-yellow-filled)" : undefined,
          }}
        >
          {style ? <span style={style}>{matchSlice}</span> : matchSlice}
        </mark>,
      );

      cursor = overlapEnd;
      if (m.end <= tokenEnd) {
        localMatchIdx += 1;
      } else {
        break;
      }
    }

    if (cursor < tokenEnd) {
      const tail = token.text.slice(cursor - tokenStart);
      nodes.push(
        style ? (
          <span key={`${tIdx}:tail:${cursor}`} style={style}>
            {tail}
          </span>
        ) : (
          <Fragment key={`${tIdx}:tail:${cursor}`}>{tail}</Fragment>
        ),
      );
    }

    charOffset = tokenEnd;
  }

  return nodes;
}

export function DdlTab({ ddl, objectType, objectName }: DdlTabProps) {
  const t = useTranslate();
  const { open } = useNotification();
  const [search, setSearch] = useState("");
  const [activeMatch, setActiveMatch] = useState(0);
  const [wrapLines, setWrapLines] = useState(false);
  const markRefs = useRef(new Map<number, HTMLElement>());

  const lines = useMemo(() => (ddl ? ddl.split(/\r?\n/) : []), [ddl]);
  const tokenizedLines = useMemo(() => (ddl ? tokenizeSqlLines(ddl) : []), [ddl]);
  const matches = useMemo(() => findLineMatches(lines, search), [lines, search]);

  const matchesByLine = useMemo(() => {
    const map = new Map<number, Array<{ matchIndex: number; start: number; end: number }>>();
    matches.forEach((m, index) => {
      const list = map.get(m.lineIndex) ?? [];
      list.push({ matchIndex: index, start: m.start, end: m.end });
      map.set(m.lineIndex, list);
    });
    return map;
  }, [matches]);

  useEffect(() => {
    setActiveMatch(0);
  }, [search, ddl]);

  useEffect(() => {
    if (matches.length === 0) return;
    const el = markRefs.current.get(activeMatch);
    el?.scrollIntoView?.({ block: "nearest", inline: "nearest" });
  }, [activeMatch, matches.length]);

  if (!ddl) {
    const isRoutine = objectType ? !isSampleEligible(objectType) : false;
    return (
      <EmptyState
        icon={<CodeIcon size={28} aria-hidden />}
        message={t(isRoutine ? "catalog.ddl.emptyRoutine" : "catalog.ddl.emptyTable")}
      />
    );
  }

  const byteCount = new TextEncoder().encode(ddl).length;
  const statsText = t("catalog.ddl.stats", {
    lines: lines.length,
    bytes: formatByteSize(byteCount),
  });

  const stepMatch = (delta: number) => {
    if (matches.length === 0) return;
    setActiveMatch((prev) => (prev + delta + matches.length) % matches.length);
  };

  const copy = async () => {
    try {
      await copyText(ddl);
      open?.({ type: "success", message: t("common.copy.success") });
    } catch {
      open?.({
        type: "error",
        message: t("common.copy.failed"),
      });
    }
  };

  return (
    <Stack gap="sm">
      <Group justify="space-between" gap="sm" wrap="wrap">
        <Group gap="xs" wrap="wrap">
          {objectName ? (
            <Text size="xs" fw={600} ff="monospace">
              {objectName}
            </Text>
          ) : null}
          <Text size="xs" c="dimmed">
            {statsText}
          </Text>
        </Group>
        <Group gap="xs" wrap="wrap" align="center">
          <TextInput
            size="xs"
            w={200}
            aria-label={t("catalog.ddl.searchPlaceholder")}
            placeholder={t("catalog.ddl.searchPlaceholder")}
            leftSection={<SearchIcon size={14} aria-hidden />}
            rightSection={
              search ? (
                <ActionIcon
                  size="xs"
                  variant="subtle"
                  aria-label={t("common.clear")}
                  onClick={() => setSearch("")}
                >
                  <CloseIcon size={12} aria-hidden />
                </ActionIcon>
              ) : null
            }
            value={search}
            onChange={(event) => setSearch(event.currentTarget.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                event.preventDefault();
                stepMatch(event.shiftKey ? -1 : 1);
              }
            }}
          />
          {search.trim() ? (
            <Text size="xs" c="dimmed" aria-live="polite">
              {matches.length > 0
                ? t("catalog.ddl.matchCount", {
                    current: activeMatch + 1,
                    total: matches.length,
                  })
                : t("catalog.ddl.noMatches")}
            </Text>
          ) : null}
          <ActionIcon
            size="sm"
            variant="default"
            aria-label={t("catalog.ddl.prevMatch")}
            disabled={matches.length === 0}
            onClick={() => stepMatch(-1)}
          >
            <ChevronUpIcon size={14} aria-hidden />
          </ActionIcon>
          <ActionIcon
            size="sm"
            variant="default"
            aria-label={t("catalog.ddl.nextMatch")}
            disabled={matches.length === 0}
            onClick={() => stepMatch(1)}
          >
            <ChevronDownIcon size={14} aria-hidden />
          </ActionIcon>
          <Switch
            size="xs"
            label={t("catalog.ddl.wrapLines")}
            checked={wrapLines}
            onChange={(event) => setWrapLines(event.currentTarget.checked)}
          />
          <Button
            size="xs"
            variant="light"
            leftSection={<CopyIcon size={14} aria-hidden />}
            onClick={() => void copy()}
          >
            {t("catalog.ddl.copy")}
          </Button>
        </Group>
      </Group>

      <Box
        role="region"
        aria-label={objectName ? `${objectName} DDL` : "DDL"}
        bd="1px solid var(--refraq-tone-neutral-border)"
        bdrs="sm"
        bg="var(--mantine-color-body)"
        style={{
          overflowX: wrapLines ? "hidden" : "auto",
          overflowY: "auto",
          maxHeight: "65vh",
          fontFamily: "var(--mantine-font-family-monospace)",
          fontSize: "var(--mantine-font-size-xs)",
          lineHeight: 1.6,
        }}
      >
        <Box
          component="div"
          py="xs"
          px="xs"
          style={{ minWidth: wrapLines ? 0 : "max-content" }}
        >
          {tokenizedLines.map((tokens, idx) => (
            <Box
              key={idx}
              style={{
                display: "flex",
                alignItems: "flex-start",
                gap: "var(--mantine-spacing-sm)",
              }}
            >
              <Box
                component="span"
                c="dimmed"
                style={{
                  userSelect: "none",
                  textAlign: "right",
                  minWidth: "3ch",
                  flexShrink: 0,
                  paddingRight: "var(--mantine-spacing-xs)",
                  borderRight: "1px solid var(--refraq-tone-neutral-border)",
                }}
              >
                {idx + 1}
              </Box>
              <Box
                component="span"
                style={{
                  whiteSpace: wrapLines ? "pre-wrap" : "pre",
                  overflowWrap: wrapLines ? "anywhere" : "normal",
                  flex: 1,
                  minWidth: 0,
                }}
              >
                {renderTokensWithSearch(
                  tokens,
                  matchesByLine.get(idx) ?? [],
                  activeMatch,
                  markRefs,
                )}
              </Box>
            </Box>
          ))}
        </Box>
      </Box>
    </Stack>
  );
}
