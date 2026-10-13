export type TemplateMark = {
  kind: "delim" | "ref" | "node";
  from: number;
  to: number;
};

export type ExpressionSpan = {
  from: number;
  to: number;
  bodyFrom: number;
  bodyTo: number;
};

export type ScannedTemplate = {
  ok: boolean;
  wholeExpression: boolean;
  hasExpression: boolean;
  staticText: string;
  expressions: ExpressionSpan[];
  marks: TemplateMark[];
};

export type TemplateCursor =
  | { kind: "outside" }
  | { kind: "string" }
  | { kind: "nodeKey"; start: number; filter: string }
  | { kind: "code" };

const RESERVED = new Set(["nodes", "channel", "run", "platform"]);
const IDENT = /[A-Za-z_][A-Za-z0-9_]*/;

type RawScan = {
  ok: boolean;
  text: string;
  expressions: ExpressionSpan[];
  marks: TemplateMark[];
};

export function scanTemplate(text: string): ScannedTemplate {
  const scanned = scanRaw(text);
  const wholeExpression = coversTrimmed(text, scanned);
  return {
    ok: scanned.ok,
    wholeExpression,
    hasExpression: scanned.ok && scanned.expressions.length > 0,
    staticText:
      scanned.ok && scanned.expressions.length === 0 ? scanned.text.trim() : scanned.text,
    expressions: scanned.expressions,
    marks: scanned.marks,
  };
}

export function templatePosition(text: string, cursor: number): TemplateCursor {
  const span = scanTemplate(text).expressions.find(
    (item) => cursor >= item.bodyFrom && cursor <= item.bodyTo,
  );
  if (!span) return { kind: "outside" };
  return positionInBody(text, span.bodyFrom, cursor);
}

function coversTrimmed(text: string, scanned: RawScan): boolean {
  if (!scanned.ok || scanned.expressions.length !== 1) return false;
  const span = scanned.expressions[0];
  if (!span) return false;
  const lead = text.length - text.trimStart().length;
  return span.from === lead && span.to === text.trimEnd().length;
}

function scanRaw(raw: string): RawScan {
  const marks: TemplateMark[] = [];
  const expressions: ExpressionSpan[] = [];
  const textParts: string[] = [];
  let ok = true;
  let index = 0;

  while (index < raw.length) {
    if (raw[index] === "\\") {
      let end = index;
      while (end < raw.length && raw[end] === "\\") end += 1;
      const count = end - index;
      if (raw.startsWith("{{", end)) {
        textParts.push("\\".repeat(Math.floor(count / 2)));
        if (count % 2 === 1) {
          textParts.push("{{");
          index = end + 2;
          continue;
        }
        index = end;
        continue;
      }
      textParts.push("\\".repeat(count));
      index = end;
      continue;
    }
    if (raw.startsWith("{{", index)) {
      const read = readExpression(raw, index + 2);
      if (read.status === "invalid") {
        ok = false;
        break;
      }
      marks.push({ kind: "delim", from: index, to: index + 2 });
      if (read.status === "closed") {
        marks.push({ kind: "delim", from: read.index - 2, to: read.index });
      }
      markNames(raw, read.bodyFrom, read.bodyTo, marks);
      expressions.push({
        from: index,
        to: read.index,
        bodyFrom: read.bodyFrom,
        bodyTo: read.bodyTo,
      });
      if (read.status === "open" || raw.slice(read.bodyFrom, read.bodyTo).trim() === "") {
        ok = false;
      }
      index = read.index;
      if (read.status === "open") break;
      continue;
    }
    textParts.push(raw[index] ?? "");
    index += 1;
  }
  return { ok, text: textParts.join(""), expressions, marks };
}

function positionInBody(text: string, from: number, cursor: number): TemplateCursor {
  let index = from;
  let quote: string | null = null;
  let quoteStart = 0;
  let nodeKeyStart = -1;
  while (index < cursor) {
    const char = text[index] ?? "";
    if (quote !== null) {
      if (char === "\\" && quote.length === 1) {
        index += 2;
        continue;
      }
      if (text.startsWith(quote, index)) {
        index += quote.length;
        quote = null;
        nodeKeyStart = -1;
        continue;
      }
      index += 1;
      continue;
    }
    if (char === "'" || char === '"') {
      quote = text.startsWith(char.repeat(3), index) ? char.repeat(3) : char;
      quoteStart = index;
      nodeKeyStart = quote.length === 1 ? nodeKeyOrigin(text, from, index) : -1;
      index += quote.length;
      continue;
    }
    index += 1;
  }
  if (quote !== null) {
    if (nodeKeyStart >= 0) {
      return {
        kind: "nodeKey",
        start: nodeKeyStart,
        filter: text.slice(quoteStart + 1, cursor),
      };
    }
    return { kind: "string" };
  }
  const opened = openNodeKey(text, cursor);
  if (opened) return { kind: "nodeKey", start: opened, filter: "" };
  return { kind: "code" };
}

function nodeKeyOrigin(text: string, limit: number, quoteIndex: number): number {
  if (text[quoteIndex - 1] !== "[") return -1;
  const marker = "self.nodes";
  const start = quoteIndex - 1 - marker.length;
  if (start < limit || text.slice(start, quoteIndex - 1) !== marker) return -1;
  if (start > limit && isIdentChar(text[start - 1] ?? "")) return -1;
  return start;
}

function openNodeKey(text: string, cursor: number): number | null {
  const marker = "self.nodes[";
  if (!text.slice(0, cursor).endsWith(marker)) return null;
  const start = cursor - marker.length;
  if (start > 0 && isIdentChar(text[start - 1] ?? "")) return null;
  return start;
}

type ReadResult =
  | { status: "closed" | "open"; bodyFrom: number; bodyTo: number; index: number }
  | { status: "invalid" };

function readExpression(text: string, start: number): ReadResult {
  let index = start;
  let depth = 0;
  let quote: string | null = null;
  while (index < text.length) {
    const char = text[index] ?? "";
    if (quote !== null) {
      if (char === "\\" && quote.length === 1) {
        index += 2;
        continue;
      }
      if (text.startsWith(quote, index)) {
        index += quote.length;
        quote = null;
        continue;
      }
      index += 1;
      continue;
    }
    if (char === "'" || char === '"') {
      quote = text.startsWith(char.repeat(3), index) ? char.repeat(3) : char;
      index += quote.length;
      continue;
    }
    if (char === "{") {
      depth += 1;
      index += 1;
      continue;
    }
    if (char === "}") {
      if (depth > 0) {
        depth -= 1;
        index += 1;
        continue;
      }
      if (text[index + 1] === "}") {
        return { status: "closed", bodyFrom: start, bodyTo: index, index: index + 2 };
      }
      return { status: "invalid" };
    }
    index += 1;
  }
  return { status: "open", bodyFrom: start, bodyTo: text.length, index: text.length };
}

function markNames(text: string, from: number, to: number, marks: TemplateMark[]) {
  let index = from;
  let quote: string | null = null;
  while (index < to) {
    const char = text[index] ?? "";
    if (quote !== null) {
      if (char === "\\" && quote.length === 1) {
        index += 2;
        continue;
      }
      if (text.startsWith(quote, index)) {
        index += quote.length;
        quote = null;
        continue;
      }
      index += 1;
      continue;
    }
    if (char === "'" || char === '"') {
      quote = text.startsWith(char.repeat(3), index) ? char.repeat(3) : char;
      index += quote.length;
      continue;
    }
    if (isSelfDot(text, index)) {
      const after = index + "self.".length;
      if (text.startsWith("nodes", after) && !isIdentChar(text[after + "nodes".length] ?? "")) {
        const key = readNodeKey(text, after + "nodes".length, to);
        if (key) {
          marks.push({ kind: "node", from: index, to: key });
          index = key;
          continue;
        }
      } else {
        const ident = readIdent(text, after);
        if (ident && !RESERVED.has(ident)) {
          const end = after + ident.length;
          marks.push({ kind: "ref", from: index, to: end });
          index = end;
          continue;
        }
      }
    }
    index += 1;
  }
}

function isSelfDot(text: string, index: number): boolean {
  if (!text.startsWith("self.", index)) return false;
  return index === 0 || !isIdentChar(text[index - 1] ?? "");
}

function isIdentChar(char: string): boolean {
  return /[A-Za-z0-9_]/.test(char);
}

function readIdent(text: string, start: number): string | null {
  const match = IDENT.exec(text.slice(start));
  if (!match || match.index !== 0) return null;
  return match[0];
}

function readNodeKey(text: string, bracket: number, limit: number): number | null {
  if (text[bracket] !== "[") return null;
  const quote = text[bracket + 1];
  if (quote !== "'" && quote !== '"') return null;
  let index = bracket + 2;
  while (index < limit) {
    if (text[index] === "\\") {
      index += 2;
      continue;
    }
    if (text[index] === quote) {
      if (text[index + 1] !== "]") return null;
      return index + 2;
    }
    index += 1;
  }
  return null;
}
