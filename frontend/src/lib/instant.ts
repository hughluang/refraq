const INSTANT_TEXT =
  /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?)(Z|[+-]\d{2}:\d{2})$/i;

/**
 * Parsed platform Instant. Response fields stay strings; this class is only
 * for callers that already hold a validated value, such as wall-clock parts.
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

  /**
   * Epoch milliseconds of a platform Instant.
   * Null when `value` is not an offset RFC 3339 timestamp.
   */
  static epochMsOf(value: string): number | null {
    try {
      return Instant.parse(value).epochMs();
    } catch {
      return null;
    }
  }
}
