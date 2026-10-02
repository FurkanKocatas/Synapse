import { useCallback, useSyncExternalStore } from "react";

function supported(): boolean {
  return typeof window.matchMedia === "function";
}

/** Whether ``query`` matches now, kept current as the window changes. False where the browser
 * (or the test environment) has no media queries. */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      if (!supported()) return () => undefined;
      const media = window.matchMedia(query);
      media.addEventListener("change", onChange);
      return () => {
        media.removeEventListener("change", onChange);
      };
    },
    [query],
  );
  return useSyncExternalStore(subscribe, () => supported() && window.matchMedia(query).matches);
}
