import { describe, expect, it } from "vitest";

import en from "@/locales/en-US/common.json";
import zh from "@/locales/zh-CN/common.json";
import { ApiError } from "@/lib/api";
import { problemMessage } from "@/lib/problem";

const OWNED_CODES = [
  "EMAIL_ACCOUNT_IN_USE",
  "EMAIL_ACCOUNT_NOT_FOUND",
  "WEBHOOK_IN_USE",
  "WEBHOOK_URL_REJECTED",
  "WEBHOOK_NOT_FOUND",
] as const;

/** English occurrence text from the API. The main line must not repeat it. */
const SERVER_DETAIL: Record<(typeof OWNED_CODES)[number], string> = {
  EMAIL_ACCOUNT_IN_USE: "Email Account is still referenced by a Data Channel",
  EMAIL_ACCOUNT_NOT_FOUND: "Email Account not found",
  WEBHOOK_IN_USE: "Webhook is still referenced by a Data Channel",
  WEBHOOK_URL_REJECTED: "Webhook URL is not allowed",
  WEBHOOK_NOT_FOUND: "Webhook not found",
};

const dictionary: Record<string, string> = {
  "problems.USER_GROUP_KEY_DUPLICATE": "That user group key is taken",
  "problems.unknown": "Something went wrong",
};

function t(key: string): string {
  return dictionary[key] ?? key;
}

describe("problemMessage", () => {
  it("uses the Problem Code entry when one exists", () => {
    const error = new ApiError(
      409,
      "USER_GROUP_KEY_DUPLICATE",
      "User Group key already exists",
    );
    expect(problemMessage(t, error, "failed")).toBe("That user group key is taken");
  });

  it("does not return raw English detail when a code is unknown", () => {
    const error = new ApiError(
      422,
      "ENTITY_ROW_INVALID",
      "Entity row values or filters are invalid",
    );
    expect(problemMessage(t, error, "failed")).toBe("Something went wrong");
    expect(problemMessage(t, error, "failed")).not.toBe(
      "Entity row values or filters are invalid",
    );
  });

  it("uses the caller fallback when the failure is not an API error", () => {
    expect(problemMessage(t, new Error("nope"), "load failed")).toBe("load failed");
  });
});

const SAVED_FILTER_CODES = [
  "SAVED_FILTER_LIMIT",
  "SAVED_FILTER_NAME_CONFLICT",
  "SAVED_FILTER_NAME_INVALID",
  "SAVED_FILTER_NOT_FOUND",
] as const;

const SAVED_FILTER_DETAIL: Record<(typeof SAVED_FILTER_CODES)[number], string> = {
  SAVED_FILTER_LIMIT: "A list can keep at most 20 saved filters",
  SAVED_FILTER_NAME_CONFLICT: "A saved filter with this name already exists",
  SAVED_FILTER_NAME_INVALID: "Saved filter name is not valid",
  SAVED_FILTER_NOT_FOUND: "Saved filter not found",
};

describe("saved filter problem codes", () => {
  it.each([
    ["en-US", en],
    ["zh-CN", zh],
  ] as const)("%s states the refusal and does not ask for a retry", (_locale, catalog) => {
    const translate = (key: string) => catalog[key as keyof typeof catalog] ?? key;
    for (const code of SAVED_FILTER_CODES) {
      const key = `problems.${code}`;
      const copy = translate(key);
      expect(copy).not.toBe(key);
      expect(copy).not.toBe(translate("problems.unknown"));
      expect(copy.toLowerCase()).not.toContain("retry");
      expect(copy.toLowerCase()).not.toContain("try again");
      const message = problemMessage(
        translate,
        new ApiError(422, code, SAVED_FILTER_DETAIL[code], "req-1"),
        "failed",
      );
      expect(message).toBe(copy);
      expect(message).not.toBe(SAVED_FILTER_DETAIL[code]);
    }
  });
});

const TAG_IN_USE_DETAIL = "Tag is still assigned";

function catalogTranslate(catalog: Record<string, string>) {
  return (key: string, options?: Record<string, string>) => {
    const template = catalog[key] ?? key;
    if (!options) return template;
    return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => options[name] ?? "");
  };
}

describe("TAG_IN_USE", () => {
  it.each([
    ["en-US", en],
    ["zh-CN", zh],
  ] as const)("%s states both counts and leaves server detail out of the main line", (_locale, catalog) => {
    const translate = catalogTranslate(catalog);
    const message = problemMessage(
      translate,
      new ApiError(409, "TAG_IN_USE", TAG_IN_USE_DETAIL, "req-1", {
        entity_count: 1,
        channel_count: 0,
      }),
      "failed",
    );
    expect(message).toContain("1");
    expect(message).toContain("0");
    expect(message).not.toBe(TAG_IN_USE_DETAIL);
    expect(message).not.toContain("{{");
    expect(message).not.toBe(translate("problems.TAG_IN_USE_BARE"));
  });

  it.each([
    ["en-US", en],
    ["zh-CN", zh],
  ] as const)("%s uses the sentence without counts when an extension is missing", (_locale, catalog) => {
    const translate = catalogTranslate(catalog);
    const message = problemMessage(
      translate,
      new ApiError(409, "TAG_IN_USE", TAG_IN_USE_DETAIL, "req-1", {
        entity_count: 1,
      }),
      "failed",
    );
    expect(message).toBe(translate("problems.TAG_IN_USE_BARE"));
    expect(message).not.toMatch(/\d/);
    expect(message).not.toBe(TAG_IN_USE_DETAIL);
  });

  it("does not treat a non-integer extension as a count", () => {
    const translate = catalogTranslate(en);
    const message = problemMessage(
      translate,
      new ApiError(409, "TAG_IN_USE", TAG_IN_USE_DETAIL, "req-1", {
        entity_count: 1,
        channel_count: "0",
      }),
      "failed",
    );
    expect(message).toBe(translate("problems.TAG_IN_USE_BARE"));
  });
});

describe("email account and webhook problem codes", () => {
  it.each([
    ["en-US", en],
    ["zh-CN", zh],
  ] as const)("%s localizes owned codes and leaves server detail out of the main line", (_locale, catalog) => {
    const translate = (key: string) => catalog[key as keyof typeof catalog] ?? key;
    for (const code of OWNED_CODES) {
      const key = `problems.${code}`;
      const copy = translate(key);
      expect(copy).not.toBe(key);
      expect(copy).not.toBe(translate("problems.unknown"));
      const message = problemMessage(
        translate,
        new ApiError(409, code, SERVER_DETAIL[code], "req-1"),
        "failed",
      );
      expect(message).toBe(copy);
      expect(message).not.toBe(SERVER_DETAIL[code]);
    }
  });
});
