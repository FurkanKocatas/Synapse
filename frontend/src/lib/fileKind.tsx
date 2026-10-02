import {
  FileDocIcon,
  FileImageIcon,
  FilePdfIcon,
  FilePptIcon,
  FileTextIcon,
  FileXlsIcon,
  type Icon,
} from "@phosphor-icons/react";

import { cn } from "@/lib/utils";

// The colours people know these formats by, so a list can be scanned by type at a glance.
const KINDS = {
  pdf: { icon: FilePdfIcon, tone: "text-file-pdf" },
  doc: { icon: FileDocIcon, tone: "text-file-doc" },
  sheet: { icon: FileXlsIcon, tone: "text-file-sheet" },
  slides: { icon: FilePptIcon, tone: "text-file-slides" },
  image: { icon: FileImageIcon, tone: "text-muted-foreground" },
  other: { icon: FileTextIcon, tone: "text-muted-foreground" },
} satisfies Record<string, { icon: Icon; tone: string }>;

type Kind = keyof typeof KINDS;

const BY_EXTENSION: Record<string, Kind> = {
  pdf: "pdf",
  docx: "doc",
  odt: "doc",
  xlsx: "sheet",
  ods: "sheet",
  csv: "sheet",
  pptx: "slides",
  odp: "slides",
  png: "image",
  jpg: "image",
  jpeg: "image",
  tif: "image",
  tiff: "image",
  webp: "image",
};

/** The kind of a file, from its media type, or from the extension of its name. */
export function fileKind(mediaType: string | null, name: string): Kind {
  if (mediaType !== null) {
    if (mediaType === "application/pdf") return "pdf";
    if (mediaType.includes("wordprocessingml") || mediaType.includes("opendocument.text"))
      return "doc";
    if (mediaType.includes("spreadsheetml") || mediaType === "text/csv") return "sheet";
    if (mediaType.includes("presentationml")) return "slides";
    if (mediaType.startsWith("image/")) return "image";
  }
  const extension = /\.([a-z0-9]+)$/i.exec(name)?.[1]?.toLocaleLowerCase("en") ?? "";
  return BY_EXTENSION[extension] ?? "other";
}

export function FileIcon({
  mediaType = null,
  name,
  className,
}: {
  mediaType?: string | null;
  name: string;
  className?: string;
}) {
  const { icon: IconFor, tone } = KINDS[fileKind(mediaType, name)];
  return (
    <IconFor weight="fill" className={cn("size-4 shrink-0", tone, className)} aria-hidden="true" />
  );
}
