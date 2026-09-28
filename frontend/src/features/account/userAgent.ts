// A short, readable name for the device behind a session ("Chrome · macOS"), so users can tell
// their sessions apart. Only common browsers and systems are named; anything else is left out
// rather than guessed.

const BROWSERS: [RegExp, string][] = [
  [/Edg\//, "Edge"],
  [/OPR\//, "Opera"],
  [/Firefox\//, "Firefox"],
  [/Chrome\//, "Chrome"], // after Edge and Opera, which also say Chrome
  [/Safari\//, "Safari"], // after Chrome, which also says Safari
];

const SYSTEMS: [RegExp, string][] = [
  [/Windows/, "Windows"],
  [/Android/, "Android"], // before Linux, which Android also says
  [/iPhone|iPad/, "iOS"], // before macOS, which iOS also says
  [/Mac OS X/, "macOS"],
  [/Linux/, "Linux"],
];

function first(patterns: [RegExp, string][], text: string): string | undefined {
  return patterns.find(([pattern]) => pattern.test(text))?.[1];
}

export function describeUserAgent(userAgent: string | null): string | null {
  if (!userAgent) return null;
  const parts = [first(BROWSERS, userAgent), first(SYSTEMS, userAgent)].filter(
    (part): part is string => part !== undefined,
  );
  return parts.length > 0 ? parts.join(" · ") : null;
}
