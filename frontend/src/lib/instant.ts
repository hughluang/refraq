import operations from "@/lib/api-time-fields.generated.json";

const INSTANT_TEXT =
  /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?)(Z|[+-]\d{2}:\d{2})$/i;

/**
 * API timestamp. A class so it is not a string and not a React node: the only
 * display paths are `<Instant>` and `useFormatInstant`.
 */
export class Instant {
  readonly #ms: number;

  private constructor(ms: number) {
    this.#ms = ms;
  }

  /** Milliseconds since the Unix epoch. Valid by construction. */
  epochMs(): number {
    return this.#ms;
  }

  /** ISO-8601 for `JSON.stringify`. Display must not use this. */
  toJSON(): string {
    return new Date(this.#ms).toISOString();
  }

  /** Build an Instant. Throws when `value` is not an offset RFC 3339 timestamp. */
  static parse(value: string): Instant {
    if (!INSTANT_TEXT.test(value)) {
      throw new Error(`invalid Instant: ${value}`);
    }
    const ms = Date.parse(value);
    if (Number.isNaN(ms)) {
      throw new Error(`invalid Instant: ${value}`);
    }
    return new Instant(ms);
  }
}

/** The response does not match the OpenAPI Instant contract. */
export class ApiContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "ApiContractError";
  }
}

type CompiledOperation = {
  method: string;
  template: string;
  pattern: RegExp;
  literals: number;
  paths: readonly string[];
};

function compileTemplate(template: string): { pattern: RegExp; literals: number } {
  let literals = 0;
  const source = template
    .split("/")
    .map((segment) => {
      if (segment.startsWith("{") && segment.endsWith("}")) return "[^/]+";
      if (segment.length > 0) literals += 1;
      return segment.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    })
    .join("/");
  return { pattern: new RegExp(`^${source}$`), literals };
}

const compiled: CompiledOperation[] = Object.entries(operations).map(
  ([key, paths]) => {
    const space = key.indexOf(" ");
    const method = key.slice(0, space);
    const template = key.slice(space + 1);
    const { pattern, literals } = compileTemplate(template);
    return { method, template, pattern, literals, paths };
  },
);

function pathnameOf(path: string): string {
  const stop = path.search(/[?#]/);
  const pathname = stop === -1 ? path : path.slice(0, stop);
  return pathname.startsWith("/") ? pathname : `/${pathname}`;
}

/**
 * Instant paths for one success response.
 * Every `apiClient` call must match an OpenAPI operation. Direct fetches that
 * are not `apiClient` (`app/mcp/route.ts`, public branding in
 * `features/branding/server.ts`) are outside this map and carry no Instant fields.
 */
export function timeFieldPaths(method: string, path: string): readonly string[] {
  const verb = method.toUpperCase();
  const pathname = pathnameOf(path);
  const hits = compiled.filter(
    (item) => item.method === verb && item.pattern.test(pathname),
  );
  if (hits.length === 0) {
    throw new ApiContractError(`no OpenAPI operation for ${verb} ${pathname}`);
  }
  hits.sort(
    (a, b) => b.literals - a.literals || b.template.length - a.template.length,
  );
  return hits[0].paths;
}

function coerceInstant(value: unknown, path: string): Instant | null {
  if (value === null) return null;
  if (typeof value !== "string") {
    throw new ApiContractError(`${path} is not an Instant string`);
  }
  try {
    return Instant.parse(value);
  } catch {
    throw new ApiContractError(`${path} is not an Instant: ${value}`);
  }
}

function applyPath(
  node: unknown,
  segments: readonly [string, ...string[]],
  full: string,
): void {
  const [head, ...rest] = segments;
  const array = head.endsWith("[]");
  const key = array ? head.slice(0, -2) : head;

  if (array && key === "") {
    if (!Array.isArray(node)) {
      throw new ApiContractError(`${full} is not an array`);
    }
    for (let index = 0; index < node.length; index += 1) {
      if (rest.length === 0) node[index] = coerceInstant(node[index], full);
      else if (node[index] != null) {
        applyPath(node[index], rest as [string, ...string[]], full);
      }
    }
    return;
  }

  if (node === null || typeof node !== "object" || Array.isArray(node)) {
    throw new ApiContractError(`${full} parent is not an object`);
  }
  const record = node as Record<string, unknown>;
  if (!(key in record) || record[key] == null) return;

  const value = record[key];
  if (array) {
    if (!Array.isArray(value)) {
      throw new ApiContractError(`${full} is not an array`);
    }
    for (let index = 0; index < value.length; index += 1) {
      if (rest.length === 0) value[index] = coerceInstant(value[index], full);
      else if (value[index] != null) {
        applyPath(value[index], rest as [string, ...string[]], full);
      }
    }
    return;
  }
  if (rest.length === 0) {
    record[key] = coerceInstant(value, full);
    return;
  }
  applyPath(value, rest as [string, ...string[]], full);
}

/** Replace declared Instant strings in a success body. `null` stays `null`. */
export function decodeResponseInstants(
  method: string,
  path: string,
  body: unknown,
): unknown {
  const paths = timeFieldPaths(method, path);
  if (paths.length === 0) return body;
  if (paths.includes("$")) {
    if (paths.length !== 1) {
      throw new ApiContractError(`mixed root Instant for ${method} ${path}`);
    }
    return coerceInstant(body, "$");
  }
  if (body === null || typeof body !== "object") {
    throw new ApiContractError(`expected a JSON object for ${method} ${path}`);
  }
  for (const item of paths) {
    applyPath(body, item.split(".") as [string, ...string[]], item);
  }
  return body;
}
