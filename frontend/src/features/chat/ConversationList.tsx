import { ChatTeardropTextIcon, MagnifyingGlassIcon } from "@phosphor-icons/react";
import { useQuery } from "@tanstack/react-query";
import { Link, useLocation, useSearch } from "@tanstack/react-router";
import { useState, type CSSProperties } from "react";

import { cn } from "@/lib/utils";
import { m } from "@/paraglide/messages.js";
import { getLocale } from "@/paraglide/runtime.js";

import { CHAT_PATH, chatApi, conversationsKey, modeOf, type ConversationSummary } from "./chatApi";
import { ConversationActions } from "./ConversationActions";

const DAY = 24 * 60 * 60 * 1000;

/** "today", "yesterday", "this week" or "older", by the local calendar. */
function age(updatedAt: string, now: Date): () => string {
  const midnight = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
  const at = new Date(updatedAt).getTime();
  if (at >= midnight) return m.chat_group_today;
  if (at >= midnight - DAY) return m.chat_group_yesterday;
  if (at >= midnight - 6 * DAY) return m.chat_group_week;
  return m.chat_group_older;
}

/** Past conversations in the navigation, newest first, grouped by day, with a filter. */
export function ConversationList({ onNavigate }: { onNavigate?: (() => void) | undefined }) {
  const { pathname } = useLocation();
  // The open chat's conversations (the corporate chat's elsewhere, as in the library).
  const mode = modeOf(pathname);
  const conversations = useQuery({
    queryKey: conversationsKey(mode),
    queryFn: () => chatApi.conversations(mode),
  });
  const { c: openId } = useSearch({ strict: false });
  const [filter, setFilter] = useState("");
  const locale = getLocale();
  const wanted = filter.trim().toLocaleLowerCase(locale);
  const shown = (conversations.data ?? []).filter(
    (item) => wanted === "" || item.title.toLocaleLowerCase(locale).includes(wanted),
  );
  const now = new Date();
  const groups: { label: string; items: ConversationSummary[] }[] = [];
  for (const item of shown) {
    const label = age(item.updated_at, now)();
    const last = groups.at(-1);
    if (last?.label === label) last.items.push(item);
    else groups.push({ label, items: [item] });
  }

  return (
    <div className="mt-2 flex min-h-0 flex-1 flex-col">
      <label className="flex h-10 shrink-0 items-center gap-3 rounded-xl px-3 text-[14.5px] text-muted-foreground transition-colors hover:bg-accent focus-within:bg-card focus-within:shadow-[inset_0_0_0_1px_var(--input)]">
        <MagnifyingGlassIcon className="size-[18px] shrink-0" aria-hidden="true" />
        <span className="sr-only">{m.chat_search()}</span>
        <input
          type="search"
          value={filter}
          placeholder={m.chat_search()}
          onChange={(event) => {
            setFilter(event.target.value);
          }}
          className="min-w-0 flex-1 bg-transparent text-foreground outline-none placeholder:text-muted-foreground [&::-webkit-search-cancel-button]:hidden"
        />
      </label>
      <nav
        aria-label={m.chat_conversations()}
        className="-mx-1 mt-1 min-h-0 flex-1 overflow-y-auto px-1 pb-2 [scrollbar-width:thin]"
      >
        {conversations.data?.length === 0 && (
          <p className="px-2.5 py-2 text-xs text-muted-foreground">{m.chat_none()}</p>
        )}
        {groups.map((group) => (
          <section key={group.label}>
            <h2 className="px-3 pt-4 pb-1.5 text-xs font-semibold tracking-wide text-muted-foreground">
              {group.label}
            </h2>
            <ul className="flex flex-col gap-0.5">
              {group.items.map((item) => {
                const current = pathname === CHAT_PATH[mode] && item.id === openId;
                return (
                  <li
                    key={item.id}
                    style={{ "--i": shown.indexOf(item) } as CSSProperties}
                    className={cn(
                      "group/item relative flex h-9 animate-rise items-center rounded-xl text-[14.5px] text-subtle-foreground transition-colors hover:bg-accent hover:text-foreground",
                      current && "bg-accent font-medium text-foreground",
                    )}
                  >
                    <ChatTeardropTextIcon
                      weight={current ? "fill" : "regular"}
                      className={cn(
                        "ml-3 size-4 shrink-0 text-muted-foreground transition-colors group-hover/item:text-secondary-foreground",
                        current && "text-secondary-foreground",
                      )}
                      aria-hidden="true"
                    />
                    <Link
                      to={CHAT_PATH[mode]}
                      search={{ c: item.id }}
                      onClick={onNavigate}
                      aria-current={current ? "page" : undefined}
                      className="min-w-0 flex-1 truncate rounded-lg py-2 pr-1 pl-2.5 outline-none focus-visible:ring-2 focus-visible:ring-ring"
                    >
                      {item.title}
                    </Link>
                    <ConversationActions
                      conversation={item}
                      label={`${m.chat_actions()}: ${item.title}`}
                      className={cn(
                        "mr-0.5 opacity-0 group-hover/item:opacity-100 focus-visible:opacity-100 data-[popup-open]:opacity-100 pointer-coarse:opacity-100",
                        current && "opacity-100",
                      )}
                    />
                  </li>
                );
              })}
            </ul>
          </section>
        ))}
      </nav>
    </div>
  );
}
