import { PreviewCard } from "@base-ui/react/preview-card";
import { ArrowSquareOutIcon } from "@phosphor-icons/react";
import { motion } from "motion/react";
import { useEffect, useRef } from "react";

import { floatingPanel } from "@/components/ui/menu";
import { FileIcon } from "@/lib/fileKind";
import { cn } from "@/lib/utils";
import { m } from "@/paraglide/messages.js";

import { answerParts, type Source } from "./chatApi";

function pages(source: Source): string {
  return source.page_start === source.page_end
    ? m.chat_page({ page: String(source.page_start) })
    : m.chat_pages({ start: String(source.page_start), end: String(source.page_end) });
}

function sectionOf(source: Source): string | undefined {
  return source.heading_path.at(-1);
}

/** The sources as a row of cards. Before the reranker has answered they are shown faint and
 * unnumbered; when it has, each card moves to its place and takes its number. */
export function SourceRow({
  sources,
  title,
  showTitle,
  ranked,
  live,
  linked,
  onOpen,
}: {
  sources: Source[];
  title: string;
  // Being answered now: the cards arrive one after another (stored ones are simply there).
  live: boolean;
  // The title is for screen readers when the answer above already says what these are.
  showTitle: boolean;
  ranked: boolean;
  // The source whose citation is being looked at.
  linked: number | null;
  onOpen: (source: Source) => void;
}) {
  const row = useRef<HTMLOListElement>(null);
  // When the ranked order arrives the best source is first: show the row from its start.
  useEffect(() => {
    if (ranked) row.current?.scrollTo({ left: 0 });
  }, [ranked]);

  return (
    <section aria-label={title} className="mt-4">
      <h3 className={cn(showTitle ? "mb-2 text-xs font-medium text-muted-foreground" : "sr-only")}>
        {title}
      </h3>
      <ol
        ref={row}
        className="-mx-1 flex gap-2 overflow-x-auto px-1 pt-0.5 pb-2 [overflow-anchor:none] [scrollbar-width:none]"
      >
        {sources.map((source, index) => (
          <motion.li
            key={`${source.document_id}:${String(source.ordinal)}`}
            layout="position"
            initial={live ? { opacity: 0, y: 6 } : false}
            animate={{ opacity: ranked ? 1 : 0.55, y: 0 }}
            transition={{ duration: 0.35, ease: [0.2, 0, 0, 1], delay: ranked ? 0 : index * 0.045 }}
            className="w-52 shrink-0"
          >
            <button
              type="button"
              disabled={source.text === null}
              onClick={() => {
                onOpen(source);
              }}
              className={cn(
                "lift flex h-full w-full flex-col gap-1.5 rounded-xl border bg-card px-3 py-2.5 text-left shadow-raised outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60",
                linked === source.number && "border-primary shadow-floating",
              )}
            >
              <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                <FileIcon name={source.title} />
                {pages(source)}
                <span
                  className={cn(
                    "ml-auto inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-[5px] bg-muted px-1 font-mono text-[11px] text-subtle-foreground transition-opacity",
                    !ranked && "opacity-0",
                  )}
                >
                  {source.number}
                </span>
              </span>
              <span className="line-clamp-2 text-[13px] leading-snug font-medium">
                {source.text === null ? m.chat_source_gone() : source.title}
              </span>
              {sectionOf(source) !== undefined && (
                <span className="truncate text-xs text-muted-foreground">{sectionOf(source)}</span>
              )}
            </button>
          </motion.li>
        ))}
      </ol>
    </section>
  );
}

/** The answer's sentences, each followed by the numbers of the sources it rests on. While the
 * answer is written, each new piece arrives with a short fade. */
export function AnswerText({
  text,
  sources,
  live,
  onOpen,
  onLook,
}: {
  text: string;
  sources: Source[];
  live: boolean;
  onOpen: (source: Source) => void;
  onLook: (number: number | null) => void;
}) {
  return (
    <p className="mt-4 text-base leading-[1.75] text-pretty whitespace-pre-wrap">
      {answerParts(text).map((part, index) =>
        "text" in part ? (
          // Parts only grow at the end, so their position is their identity.
          <span key={index} className={cn(live && "animate-arrive")}>
            {part.text}
          </span>
        ) : (
          <span key={index} className="whitespace-nowrap">
            {part.citations.map((number) => (
              <Citation
                key={number}
                source={sources.find((source) => source.number === number)}
                number={number}
                live={live}
                onOpen={onOpen}
                onLook={onLook}
              />
            ))}
          </span>
        ),
      )}
    </p>
  );
}

/** A source number after a sentence: hovering shows the passage, clicking opens its page. */
function Citation({
  source,
  number,
  live,
  onOpen,
  onLook,
}: {
  source: Source | undefined;
  number: number;
  live: boolean;
  onOpen: (source: Source) => void;
  onLook: (number: number | null) => void;
}) {
  if (source === undefined) return null;
  const gone = source.text === null;
  return (
    <PreviewCard.Root
      onOpenChange={(open) => {
        onLook(open ? number : null);
      }}
    >
      <PreviewCard.Trigger
        delay={250}
        closeDelay={150}
        render={
          <button
            type="button"
            aria-label={m.chat_citation_label({ number: String(number) })}
            disabled={gone}
            onClick={() => {
              onOpen(source);
            }}
            className={cn(
              "ml-[3px] inline-flex h-[18px] min-w-[18px] items-center justify-center rounded-[5px] bg-muted px-1 align-[2px] font-mono text-[11px] leading-none font-medium text-subtle-foreground transition-colors outline-none hover:bg-secondary hover:text-secondary-foreground focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-60 data-[popup-open]:bg-secondary data-[popup-open]:text-secondary-foreground",
              live && "animate-arrive",
            )}
          />
        }
      >
        {number}
      </PreviewCard.Trigger>
      {!gone && (
        <PreviewCard.Portal>
          <PreviewCard.Positioner sideOffset={8} className="z-50">
            <PreviewCard.Popup className={`${floatingPanel} w-80 p-3 text-sm`}>
              <p className="flex items-center gap-2 font-medium">
                <FileIcon name={source.title} />
                <span className="truncate">{source.title}</span>
              </p>
              <p className="mt-0.5 ml-6 text-xs text-muted-foreground">
                {[pages(source), sectionOf(source)].filter(Boolean).join(" · ")}
              </p>
              <blockquote className="mt-2 line-clamp-4 border-l-2 border-highlight pl-2.5 text-[13px] leading-relaxed text-subtle-foreground">
                {source.text}
              </blockquote>
              <div className="mt-2 flex justify-end">
                <button
                  type="button"
                  onClick={() => {
                    onOpen(source);
                  }}
                  className="inline-flex h-7 items-center gap-1.5 rounded-md px-2 text-[13px] font-medium text-secondary-foreground hover:bg-secondary"
                >
                  <ArrowSquareOutIcon className="size-4" aria-hidden="true" />
                  {m.chat_open_page()}
                </button>
              </div>
            </PreviewCard.Popup>
          </PreviewCard.Positioner>
        </PreviewCard.Portal>
      )}
    </PreviewCard.Root>
  );
}
