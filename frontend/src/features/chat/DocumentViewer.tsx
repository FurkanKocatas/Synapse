import {
  CaretLeftIcon,
  CaretRightIcon,
  DownloadSimpleIcon,
  HighlighterIcon,
  ScanIcon,
  XIcon,
} from "@phosphor-icons/react";
import { useQuery } from "@tanstack/react-query";
import { motion } from "motion/react";
import { useEffect, useRef, useState } from "react";

import { IconButton } from "@/components/ui/IconButton";
import { errorMessage } from "@/features/auth/errors";
import { libraryApi } from "@/features/library/libraryApi";
import { apiRequest } from "@/lib/api";
import { FileIcon } from "@/lib/fileKind";
import { useMediaQuery } from "@/lib/useMediaQuery";
import { m } from "@/paraglide/messages.js";

import { passageRanges, type Source } from "./chatApi";
import { PdfPage } from "./PdfPage";

interface PageChunk {
  ordinal: number;
  text: string;
  page_start: number;
  page_end: number;
}

export interface DocumentPage {
  document_id: string;
  title: string;
  version: number;
  number: number;
  pages: number;
  kind: string;
  label: string | null;
  text: string;
  text_source: "layer" | "ocr";
  media_type: string;
  chunks: PageChunk[];
}

export function pageQuery(documentId: string, version: number, number: number) {
  return {
    queryKey: ["viewer", documentId, version, number],
    queryFn: () =>
      apiRequest<DocumentPage>(
        "GET",
        `/api/documents/${documentId}/versions/${String(version)}/pages/${String(number)}`,
      ),
  };
}

const WIDTH = 560;
const EASE = [0.32, 0.72, 0, 1] as const;

/** What the viewer opens: a citation's page and passage, or (from the documents page) a
 * document's first page with no passage to mark. */
export type Viewed = Pick<
  Source,
  "document_id" | "title" | "version" | "page_start" | "page_end"
> & {
  ordinal: number | null;
};

/** The page a citation points to, its cited passage highlighted, in a panel beside the page.
 * On wide screens the page makes room for it; on narrow ones it slides over the page. */
export function DocumentViewer({ source, onClose }: { source: Viewed; onClose: () => void }) {
  const [number, setNumber] = useState(source.page_start);
  const page = useQuery(pageQuery(source.document_id, source.version, number));
  const close = useRef<HTMLButtonElement>(null);
  const beside = useMediaQuery("(min-width: 1280px)");

  useEffect(() => {
    close.current?.focus();
    function onKey(event: KeyboardEvent) {
      if (event.key === "Escape") onClose();
    }
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  const cited = page.data?.chunks.find((chunk) => chunk.ordinal === source.ordinal);
  const total = page.data?.pages ?? source.page_end;
  const pdf = page.data?.media_type === "application/pdf";

  return (
    <motion.aside
      role="dialog"
      aria-modal="false"
      aria-label={m.viewer_title()}
      className={
        beside
          ? "relative flex shrink-0 justify-end overflow-hidden border-l bg-card"
          : "fixed inset-y-0 right-0 z-30 flex w-[min(35rem,100vw)] border-l bg-card shadow-floating"
      }
      initial={beside ? { width: 0 } : { x: "100%" }}
      animate={beside ? { width: WIDTH } : { x: 0 }}
      exit={beside ? { width: 0 } : { x: "100%" }}
      transition={{ type: "tween", ease: EASE, duration: 0.38 }}
    >
      <div className="flex h-full w-full min-w-0 flex-col xl:w-[560px] xl:shrink-0">
        <header className="flex h-13 shrink-0 items-center gap-2.5 border-b pr-2 pl-4">
          <FileIcon mediaType={page.data?.media_type ?? null} name={source.title} />
          <div className="min-w-0 flex-1 leading-tight">
            <h2 className="truncate text-[13.5px] font-medium">{source.title}</h2>
            <p className="text-xs text-muted-foreground">
              {m.viewer_page_of({ page: String(number), pages: String(total) })}
            </p>
          </div>
          <IconButton
            label={m.viewer_previous()}
            disabled={number <= 1}
            onClick={() => {
              setNumber(number - 1);
            }}
          >
            <CaretLeftIcon aria-hidden="true" />
          </IconButton>
          <IconButton
            label={m.viewer_next()}
            disabled={number >= total}
            onClick={() => {
              setNumber(number + 1);
            }}
          >
            <CaretRightIcon aria-hidden="true" />
          </IconButton>
          <a
            href={libraryApi.fileUrl(source.document_id, source.version)}
            aria-label={m.viewer_download()}
            title={m.viewer_download()}
            className="inline-flex size-8 items-center justify-center rounded-lg text-subtle-foreground transition-colors hover:bg-accent hover:text-foreground"
          >
            <DownloadSimpleIcon className="size-4" aria-hidden="true" />
          </a>
          <IconButton ref={close} label={m.viewer_close()} onClick={onClose}>
            <XIcon aria-hidden="true" />
          </IconButton>
        </header>
        {page.data !== undefined && (cited !== undefined || page.data.text_source === "ocr") && (
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b px-4 py-2 text-xs text-subtle-foreground">
            {cited !== undefined && (
              <span className="inline-flex items-center gap-1.5">
                <HighlighterIcon className="size-3.5" aria-hidden="true" />
                {m.viewer_cited()}
              </span>
            )}
            {page.data.text_source === "ocr" && (
              <span className="inline-flex items-center gap-1.5">
                <ScanIcon className="size-3.5" aria-hidden="true" />
                {m.viewer_ocr()}
              </span>
            )}
          </div>
        )}
        <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto bg-background p-4 sm:p-6">
          {page.isError && (
            <p role="alert" className="text-sm text-destructive">
              {errorMessage(page.error)}
            </p>
          )}
          {page.data === undefined ? (
            !page.isError && <p className="text-sm text-muted-foreground">{m.common_loading()}</p>
          ) : pdf ? (
            <>
              <PdfPage
                documentId={source.document_id}
                version={source.version}
                number={number}
                passage={cited?.text ?? null}
              />
              <details className="group rounded-lg border bg-card text-sm">
                <summary className="cursor-pointer px-3 py-2 text-subtle-foreground select-none">
                  {m.viewer_page_text()}
                </summary>
                <PageText text={page.data.text} passage={cited?.text ?? null} />
              </details>
            </>
          ) : (
            <div className="rounded-lg border bg-card text-sm">
              <PageText text={page.data.text} passage={cited?.text ?? null} />
            </div>
          )}
        </div>
      </div>
    </motion.aside>
  );
}

function PageText({ text, passage }: { text: string; passage: string | null }) {
  const first = useRef<HTMLElement>(null);
  const ranges = passage === null ? [] : passageRanges(text, passage);

  useEffect(() => {
    first.current?.scrollIntoView({ block: "center" });
  }, [text, passage]);

  const parts = [];
  let at = 0;
  for (const [index, [start, end]] of ranges.entries()) {
    if (start > at) parts.push(<span key={`t${String(at)}`}>{text.slice(at, start)}</span>);
    parts.push(
      <mark
        key={`m${String(start)}`}
        ref={index === 0 ? first : undefined}
        className="animate-highlight rounded-sm bg-transparent text-inherit"
      >
        {text.slice(start, end)}
      </mark>,
    );
    at = end;
  }
  if (at < text.length) parts.push(<span key={`t${String(at)}`}>{text.slice(at)}</span>);
  return <div className="p-3 leading-relaxed whitespace-pre-wrap">{parts}</div>;
}
