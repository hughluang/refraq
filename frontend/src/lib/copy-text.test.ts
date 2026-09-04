/** @vitest-environment jsdom */

import { afterEach, describe, expect, it, vi } from "vitest";

import { copyText } from "./copy-text";

function setSecureContext(value: boolean) {
  Object.defineProperty(window, "isSecureContext", {
    configurable: true,
    value,
  });
}

function installExecCommand(impl?: (commandId: string) => boolean) {
  const fn = vi.fn(impl ?? (() => true));
  Object.defineProperty(document, "execCommand", {
    configurable: true,
    writable: true,
    value: fn,
  });
  return fn;
}

describe("copyText", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("uses writeText when the async clipboard is available", async () => {
    setSecureContext(true);
    const writeText = vi.fn().mockResolvedValue(undefined);
    const execCommand = installExecCommand();
    Object.assign(navigator, { clipboard: { writeText } });

    await copyText("hello");

    expect(writeText).toHaveBeenCalledWith("hello");
    expect(execCommand).not.toHaveBeenCalled();
  });

  it("uses execCommand when the clipboard API is missing", async () => {
    setSecureContext(false);
    Object.assign(navigator, { clipboard: undefined });
    const execCommand = installExecCommand(() => {
      const el = document.body.querySelector("textarea");
      expect(el?.value).toBe("payload");
      return true;
    });

    await copyText("payload");

    expect(execCommand).toHaveBeenCalledWith("copy");
  });

  it("does not fall back to execCommand when writeText rejects", async () => {
    setSecureContext(true);
    const writeText = vi.fn().mockRejectedValue(new Error("denied"));
    const execCommand = installExecCommand();
    Object.assign(navigator, { clipboard: { writeText } });

    await expect(copyText("hello")).rejects.toThrow("denied");
    expect(execCommand).not.toHaveBeenCalled();
  });

  it("rejects when the insecure path cannot copy", async () => {
    setSecureContext(false);
    Object.assign(navigator, { clipboard: undefined });
    installExecCommand(() => false);

    await expect(copyText("hello")).rejects.toThrow("copy failed");
  });
});
