// One page of a PDF drawn by PDF.js, with its text layer over it and the cited passage marked
// there. PDF.js is loaded only when a PDF is opened, so the rest of the app does not carry it.

import { useQuery } from "@tanstack/react-query";
import type { PDFDocumentProxy, RenderTask } from "pdfjs-dist";
import { useEffect, useRef, useState } from "react";

import { libraryApi } from "@/features/library/libraryApi";

import { passageRanges } from "./chatApi";
import "./pdf-text-layer.css";

type PdfJs = typeof import("pdfjs-dist");

interface LoadedPdf {
  pdfjs: PdfJs;
  document: PDFDocumentProxy;
}

async function loadPdf(documentId: string, version: number): Promise<LoadedPdf> {
  const [pdfjs, worker, response] = await Promise.all([
    import("pdfjs-dist"),
    import("pdfjs-dist/build/pdf.worker.min.mjs?url"),
    fetch(libraryApi.fileUrl(documentId, version), { credentials: "same-origin" }),
  ]);
  if (!response.ok) throw new Error(`file: ${String(response.status)}`);
  pdfjs.GlobalWorkerOptions.workerSrc = worker.default;
  const data = new Uint8Array(await response.arrayBuffer());
  const document = await pdfjs.getDocument({ data }).promise;
  return { pdfjs, document };
}

/** Marks the text layer's spans that hold part of ``passage``; how many it marked. */
export function markPassage(layer: HTMLElement, passage: string): number {
  const spans = [...layer.querySelectorAll("span")].filter((span) => span.children.length === 0);
  let text = "";
  const starts: number[] = [];
  for (const span of spans) {
    starts.push(text.length);
    text += `${span.textContent} `;
  }
  const ranges = passageRanges(text, passage);
  let marked = 0;
  spans.forEach((span, index) => {
    const start = starts[index] ?? 0;
    const end = start + span.textContent.length;
    if (ranges.some(([from, to]) => start < to && end > from)) {
      span.classList.add("cited");
      marked += 1;
    }
  });
  return marked;
}

export function PdfPage({
  documentId,
  version,
  number,
  passage,
}: {
  documentId: string;
  version: number;
  number: number;
  passage: string | null;
}) {
  const pdf = useQuery({
    queryKey: ["viewer", "pdf", documentId, version],
    queryFn: () => loadPdf(documentId, version),
    staleTime: Infinity,
  });
  const box = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const layer = useRef<HTMLDivElement>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const loaded = pdf.data;
    const frame = box.current;
    const drawing = canvas.current;
    const text = layer.current;
    if (loaded === undefined || frame === null || drawing === null || text === null) return;
    let cancelled = false;
    let task: RenderTask | null = null;
    async function draw(
      loaded: LoadedPdf,
      frame: HTMLElement,
      drawing: HTMLCanvasElement,
      text: HTMLElement,
    ) {
      const page = await loaded.document.getPage(number);
      const natural = page.getViewport({ scale: 1 });
      const viewport = page.getViewport({
        scale: (frame.clientWidth || natural.width) / natural.width,
      });
      const ratio = window.devicePixelRatio || 1;
      drawing.width = Math.floor(viewport.width * ratio);
      drawing.height = Math.floor(viewport.height * ratio);
      drawing.style.width = `${String(viewport.width)}px`;
      drawing.style.height = `${String(viewport.height)}px`;
      task = page.render({
        canvas: drawing,
        viewport,
        ...(ratio === 1 ? {} : { transform: [ratio, 0, 0, ratio, 0, 0] }),
      });
      await task.promise;
      if (cancelled) return;
      text.replaceChildren();
      text.style.setProperty("--total-scale-factor", String(viewport.scale));
      const layered = new loaded.pdfjs.TextLayer({
        textContentSource: page.streamTextContent(),
        container: text,
        viewport,
      });
      await layered.render();
      if (passage !== null) markPassage(text, passage);
    }
    draw(loaded, frame, drawing, text).catch(() => {
      if (!cancelled) setFailed(true);
    });
    return () => {
      cancelled = true;
      task?.cancel();
    };
  }, [pdf.data, number, passage]);

  if (pdf.isError || failed) return null;
  // shrink-0: in the viewer's column of flex items, a box that hides its overflow would be
  // shrunk to nothing to fit the panel.
  return (
    <div
      ref={box}
      className="relative w-full shrink-0 overflow-hidden rounded-md bg-paper shadow-floating ring-1 ring-black/5"
    >
      <canvas ref={canvas} className="block" />
      <div ref={layer} className="textLayer" />
    </div>
  );
}
