import { isInteger, parse, stringify } from "lossless-json";

/** Entity IDs and integer attributes use PostgreSQL BIGINT on the wire. */
export function parseEntityDataJson(text: string): unknown {
  return parse(text, null, {
    parseNumber(token) {
      const n = Number(token);
      return isInteger(token) && !Number.isSafeInteger(n) ? BigInt(token) : n;
    },
    onDuplicateKey: ({ newValue }) => newValue,
  });
}

export function stringifyEntityDataJson(value: unknown, space?: number): string {
  const json = stringify(value, null, space);
  if (json === undefined) throw new TypeError("Expected an Entity Data JSON value");
  return json;
}
