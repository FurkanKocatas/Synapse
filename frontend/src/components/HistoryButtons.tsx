import { ArrowLeftIcon, ArrowRightIcon } from "@phosphor-icons/react";
import { useLocation, useRouter } from "@tanstack/react-router";
import { useEffect, useState } from "react";

import { IconButton } from "@/components/ui/IconButton";
import { m } from "@/paraglide/messages.js";

// The furthest entry of this tab's history the app has been to. The entries after the current
// one are there until a page is opened from it, which drops them. Kept for the tab, so a
// reload remembers them.
const FURTHEST = "synapse.history.furthest";

// The router numbers the entries of the tab's history from 0 (the first page of the app).
function indexOf(state: unknown): number {
  const index = (state as { __TSR_index?: unknown } | null)?.__TSR_index;
  return typeof index === "number" ? index : 0;
}

// Where forward can go when the app loads: nowhere after a page opened afresh (a new entry
// drops the ones after it); what was remembered after a reload or the browser's own arrows.
function initial(index: number): number {
  try {
    const [load] = performance.getEntriesByType("navigation") as PerformanceNavigationTiming[];
    if (load?.type === "navigate") return index;
    return Math.max(Number(sessionStorage.getItem(FURTHEST)) || 0, index);
  } catch {
    return index;
  }
}

/** Back and forward, as the browser's own arrows, at the top left of every page: for a window
 * without them (an app window, a kiosk) and for anyone who looks for them there. */
export function HistoryButtons() {
  const router = useRouter();
  const index = indexOf(useLocation({ select: (location) => location.state }));
  const [furthest, setFurthest] = useState(() => initial(index));

  useEffect(
    () =>
      router.history.subscribe(({ location, action }) => {
        const now = indexOf(location.state);
        setFurthest((before) => (action.type === "PUSH" ? now : Math.max(before, now)));
      }),
    [router],
  );
  useEffect(() => {
    try {
      sessionStorage.setItem(FURTHEST, String(furthest));
    } catch {
      // Not kept: forward stays off after a reload until the user goes back again.
    }
  }, [furthest]);

  return (
    <div className="flex shrink-0 items-center">
      <IconButton
        label={m.nav_back()}
        disabled={index === 0}
        onClick={() => {
          router.history.back();
        }}
      >
        <ArrowLeftIcon aria-hidden="true" />
      </IconButton>
      <IconButton
        label={m.nav_forward()}
        disabled={index >= furthest}
        onClick={() => {
          router.history.forward();
        }}
      >
        <ArrowRightIcon aria-hidden="true" />
      </IconButton>
    </div>
  );
}
