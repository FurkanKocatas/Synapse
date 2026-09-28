import { describe, expect, it } from "vitest";

import { describeUserAgent } from "./userAgent";

describe("describeUserAgent", () => {
  it.each([
    [
      "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/152.0 Safari/537.36",
      "Chrome · macOS",
    ],
    [
      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0 Safari/537.36 Edg/150.0",
      "Edge · Windows",
    ],
    ["Mozilla/5.0 (X11; Linux x86_64; rv:140.0) Gecko/20100101 Firefox/140.0", "Firefox · Linux"],
    [
      "Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/150.0 Mobile Safari/537.36",
      "Chrome · Android",
    ],
    [
      "Mozilla/5.0 (iPhone; CPU iPhone OS 19_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/19.0 Mobile/15E148 Safari/604.1",
      "Safari · iOS",
    ],
  ])("names %s", (userAgent, expected) => {
    expect(describeUserAgent(userAgent)).toBe(expected);
  });

  it("leaves unknown or missing agents unnamed", () => {
    expect(describeUserAgent("curl/8.9")).toBeNull();
    expect(describeUserAgent(null)).toBeNull();
  });
});
