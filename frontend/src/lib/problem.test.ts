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
