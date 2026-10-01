import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { Button, buttonVariants } from "@/components/ui/button";
import { errorMessage } from "@/features/auth/errors";
import { libraryApi } from "@/features/library/libraryApi";
import { apiRequest } from "@/lib/api";
import { m } from "@/paraglide/messages.js";

import { passageRanges, type Source } from "./chatApi";

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

/** The page a citation points to, its cited passage highlighted, in a panel beside the chat. */
export function DocumentViewer({ source, onClose }: { source: Source; onClose: () => void }) {
  const [number, setNumber] = useState(source.page_start);
  const page = useQuery(pageQuery(source.document_id, source.version, number));
  const close = useRef<HTMLButtonElement>(null);

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

  return (
    <aside
      role="dialog"
      aria-modal="false"
      aria-label={m.viewer_title()}
      className="fixed inset-0 z-20 flex flex-col gap-3 overflow-y-auto border-l bg-background p-4 shadow-lg md:inset-y-0 md:right-0 md:left-auto md:w-[min(42rem,50vw)]"
    >
      <header className="flex items-start justify-between gap-2">
        <div>
          <h2 className="text-lg font-semibold">{source.title}</h2>
          <p className="text-sm text-muted-foreground">
            {m.viewer_page_of({ page: String(number), pages: String(total) })}
          </p>
        </div>
        <Button ref={close} variant="outline" size="sm" onClick={onClose}>
          {m.viewer_close()}
        </Button>
      </header>
      <nav className="flex flex-wrap items-center gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={number <= 1}
          onClick={() => {
            setNumber(number - 1);
          }}
        >
          {m.viewer_previous()}
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={number >= total}
          onClick={() => {
            setNumber(number + 1);
          }}
        >
          {m.viewer_next()}
        </Button>
        <a
          className={buttonVariants({ variant: "link", size: "sm" })}
          href={libraryApi.fileUrl(source.document_id, source.version)}
        >
          {m.viewer_download()}
        </a>
      </nav>
      {page.isError && <p role="alert">{errorMessage(page.error)}</p>}
      {page.data === undefined ? (
        !page.isError && <p className="text-sm text-muted-foreground">{m.common_loading()}</p>
      ) : (
        <>
          {page.data.text_source === "ocr" && (
            <p className="text-xs text-muted-foreground">{m.viewer_ocr()}</p>
          )}
          {cited !== undefined && (
            <p className="text-xs text-muted-foreground">{m.viewer_cited()}</p>
          )}
          <PageText text={page.data.text} passage={cited?.text ?? null} />
        </>
      )}
    </aside>
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
        className="bg-yellow-200 dark:bg-yellow-700"
      >
        {text.slice(start, end)}
      </mark>,
    );
    at = end;
  }
  if (at < text.length) parts.push(<span key={`t${String(at)}`}>{text.slice(at)}</span>);
  return (
    <div className="rounded-lg border p-3 text-sm leading-relaxed whitespace-pre-wrap">{parts}</div>
  );
}
