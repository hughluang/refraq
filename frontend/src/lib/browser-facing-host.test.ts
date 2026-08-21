import { describe, expect, it } from "vitest";

import {
  browserFacingHostFromEnv,
  isLoopbackHost,
  validBrowserHost,
} from "./browser-facing-host";

describe("browserFacingHostFromEnv", () => {
  it("uses the configured host", () => {
    expect(
      browserFacingHostFromEnv(
        { REFRAQ_BROWSER_FACING_HOST: " console.example:443 " },
        "evil.example",
      ),
    ).toBe("console.example:443");
  });

  it("accepts loopback request Host when unset", () => {
    expect(browserFacingHostFromEnv({}, "127.0.0.1:3000")).toBe("127.0.0.1:3000");
    expect(browserFacingHostFromEnv({}, "localhost:3000")).toBe("localhost:3000");
  });

  it("drops a public request Host when unset", () => {
    expect(browserFacingHostFromEnv({}, "evil.example")).toBeNull();
    expect(browserFacingHostFromEnv({}, "console.example.com")).toBeNull();
  });

  it("drops an invalid configured host instead of passing the request through", () => {
    expect(
      browserFacingHostFromEnv(
        { REFRAQ_BROWSER_FACING_HOST: "https://evil.example" },
        "evil.example",
      ),
    ).toBeNull();
  });
});

describe("validBrowserHost", () => {
  it("rejects scheme, userinfo, path, and control characters", () => {
    expect(validBrowserHost("https://evil.example")).toBe(false);
    expect(validBrowserHost("evil.example/path")).toBe(false);
    expect(validBrowserHost("user@evil.example")).toBe(false);
    expect(validBrowserHost("evil.example\n")).toBe(false);
    expect(isLoopbackHost("127.0.0.1:3000")).toBe(true);
  });
});
