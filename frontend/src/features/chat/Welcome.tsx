import {
  ArchiveIcon,
  ArrowRightIcon,
  ArrowUpRightIcon,
  ChatTeardropTextIcon,
  CoinsIcon,
  GavelIcon,
  type Icon,
} from "@phosphor-icons/react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "@tanstack/react-router";
import { useState, type CSSProperties } from "react";

import { BlurText } from "@/components/reactbits/BlurText";
import { SpotlightCard } from "@/components/reactbits/SpotlightCard";
import { m } from "@/paraglide/messages.js";
import { getLocale } from "@/paraglide/runtime.js";

import { chatApi, CONVERSATIONS } from "./chatApi";
import { Composer } from "./Composer";

const EXAMPLES: [() => string, Icon][] = [
  [m.chat_example_budget, CoinsIcon],
  [m.chat_example_council, GavelIcon],
  [m.chat_example_retention, ArchiveIcon],
];

const RECENT = 3;

/** "Good morning, Ayşe" and the like (the first name only), by the hour on the user's clock. */
export function greeting(displayName: string, hour: number): string {
  const name = displayName.trim().split(/\s+/)[0] ?? "";
  if (hour < 5 || hour >= 18) return m.home_greeting_evening({ name });
  if (hour < 11) return m.home_greeting_morning({ name });
  return m.home_greeting_day({ name });
}

/** "5 minutes ago", "yesterday", in the interface's language. */
function ago(at: string, now: number): string {
  const format = new Intl.RelativeTimeFormat(getLocale(), { numeric: "auto" });
  const minutes = Math.round((new Date(at).getTime() - now) / 60_000);
  if (Math.abs(minutes) < 60) return format.format(minutes, "minute");
  const hours = Math.round(minutes / 60);
  if (Math.abs(hours) < 24) return format.format(hours, "hour");
  return format.format(Math.round(hours / 24), "day");
}

/** The empty chat: a greeting, the box to ask in, example questions and the last few
 * conversations, each as a card. */
export function Welcome({
  name,
  running,
  focusKey,
  onAsk,
  onStop,
}: {
  name: string;
  running: boolean;
  focusKey: unknown;
  onAsk: (question: string) => void;
  onStop: () => void;
}) {
  // The hour is read once, when the page opens; the greeting does not change under the user.
  const [now] = useState(() => Date.now());
  const conversations = useQuery({ queryKey: CONVERSATIONS, queryFn: chatApi.conversations });
  const recent = (conversations.data ?? []).slice(0, RECENT);

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-4 sm:px-8">
      <div className="mx-auto my-auto w-full max-w-[48rem] py-10 pb-[10vh]">
        <h2 className="text-[32px] leading-tight font-semibold tracking-tight">
          <BlurText text={greeting(name, new Date(now).getHours())} />
        </h2>
        <p className="mt-2 animate-rise text-base text-subtle-foreground [--i:3]">
          {m.home_next()}
        </p>
        <div className="mt-7 animate-rise [--i:4]">
          <Composer running={running} focusKey={focusKey} onAsk={onAsk} onStop={onStop} />
        </div>

        <section className="mt-9">
          <h3 className="mb-3 text-xs font-semibold tracking-wide text-muted-foreground">
            {m.chat_examples()}
          </h3>
          <ul className="grid gap-3 sm:grid-cols-3">
            {EXAMPLES.map(([example, IconFor], index) => (
              <li
                key={example()}
                className="animate-rise"
                style={{ "--i": 5 + index } as CSSProperties}
              >
                <SpotlightCard className="lift h-full rounded-2xl border bg-card shadow-raised">
                  <button
                    type="button"
                    onClick={() => {
                      onAsk(example());
                    }}
                    className="group flex h-full w-full flex-col gap-3 rounded-2xl p-4 text-left outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <span className="flex items-center justify-between">
                      <span className="flex size-9 items-center justify-center rounded-xl bg-secondary text-secondary-foreground transition-transform duration-300 group-hover:scale-110 group-hover:-rotate-6">
                        <IconFor weight="duotone" className="size-5" aria-hidden="true" />
                      </span>
                      <ArrowRightIcon
                        className="size-4 -translate-x-1 text-muted-foreground opacity-0 transition-[opacity,translate] duration-300 group-hover:translate-x-0 group-hover:opacity-100"
                        aria-hidden="true"
                      />
                    </span>
                    <span className="text-[14.5px] leading-snug font-medium">{example()}</span>
                  </button>
                </SpotlightCard>
              </li>
            ))}
          </ul>
        </section>

        {recent.length > 0 && (
          <section className="mt-8">
            <h3 className="mb-3 text-xs font-semibold tracking-wide text-muted-foreground">
              {m.chat_recent()}
            </h3>
            <ul className="grid gap-3 sm:grid-cols-3">
              {recent.map((conversation, index) => (
                <li
                  key={conversation.id}
                  className="animate-rise"
                  style={{ "--i": 8 + index } as CSSProperties}
                >
                  <Link
                    to="/"
                    search={{ c: conversation.id }}
                    className="lift group flex h-full flex-col gap-2 rounded-2xl border bg-card p-4 shadow-raised outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <span className="flex items-center justify-between text-xs text-muted-foreground">
                      <span className="flex items-center gap-1.5">
                        <ChatTeardropTextIcon
                          weight="duotone"
                          className="size-4 text-secondary-foreground"
                          aria-hidden="true"
                        />
                        {ago(conversation.updated_at, now)}
                      </span>
                      <ArrowUpRightIcon
                        className="size-4 opacity-0 transition-opacity group-hover:opacity-100"
                        aria-hidden="true"
                      />
                    </span>
                    <span className="line-clamp-2 text-[14.5px] leading-snug font-medium">
                      {conversation.title}
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          </section>
        )}
      </div>
    </div>
  );
}
