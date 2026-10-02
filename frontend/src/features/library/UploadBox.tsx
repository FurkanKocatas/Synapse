import {
  CheckCircleIcon,
  CircleNotchIcon,
  CloudArrowUpIcon,
  UploadSimpleIcon,
} from "@phosphor-icons/react";
import { useQueryClient } from "@tanstack/react-query";
import { useRef, useState, type DragEvent } from "react";

import { Button } from "@/components/ui/button";
import { errorMessage } from "@/features/auth/errors";
import { cn } from "@/lib/utils";
import { m } from "@/paraglide/messages.js";

import { libraryApi } from "./libraryApi";

interface Problem {
  name: string;
  reason: string;
}

interface Current {
  name: string;
  position: number;
  total: number;
}

/** Uploads one file at a time, so every failure is reported against its own file; says which
 * file of how many is going, and when they are in, that they will be ready shortly. */
export function UploadBox({ collectionId }: { collectionId: string }) {
  const queryClient = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [current, setCurrent] = useState<Current | null>(null);
  const [problems, setProblems] = useState<Problem[]>([]);
  const [uploaded, setUploaded] = useState(0);
  const [dragging, setDragging] = useState(false);

  async function send(files: FileList | File[]) {
    const all = Array.from(files);
    const found: Problem[] = [];
    setUploaded(0);
    setProblems([]);
    for (const [index, file] of all.entries()) {
      setCurrent({ name: file.name, position: index + 1, total: all.length });
      try {
        await libraryApi.upload(collectionId, file);
      } catch (failure) {
        found.push({ name: file.name, reason: errorMessage(failure) });
      }
    }
    setCurrent(null);
    setProblems(found);
    setUploaded(all.length - found.length);
    await queryClient.invalidateQueries({ queryKey: ["library", "documents", collectionId] });
  }

  function drop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setDragging(false);
    if (current === null) void send(event.dataTransfer.files);
  }

  function pick() {
    input.current?.click();
  }

  return (
    <div className="flex flex-col gap-2">
      <div
        className={cn(
          "flex flex-wrap items-center gap-x-4 gap-y-3 rounded-2xl border-2 border-dashed border-input bg-card/50 px-5 py-5 transition-colors",
          dragging && "border-primary bg-secondary",
        )}
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => {
          setDragging(false);
        }}
        onDrop={drop}
      >
        <CloudArrowUpIcon
          weight="duotone"
          className="size-9 shrink-0 text-secondary-foreground"
          aria-hidden="true"
        />
        <div className="min-w-48 flex-1 text-sm">
          <p>
            <span className="font-medium">{m.library_drop_title()}</span>{" "}
            <button
              type="button"
              disabled={current !== null}
              onClick={pick}
              className="text-subtle-foreground underline decoration-input underline-offset-4 hover:text-foreground"
            >
              {m.library_drop_pick()}
            </button>
          </p>
          <p className="mt-0.5 text-xs text-muted-foreground">{m.library_drop_hint()}</p>
        </div>
        <Button type="button" disabled={current !== null} onClick={pick}>
          <UploadSimpleIcon aria-hidden="true" />
          {m.library_upload()}
        </Button>
        <input
          ref={input}
          type="file"
          multiple
          hidden
          aria-label={m.library_upload()}
          onChange={(event) => {
            if (event.target.files) void send(event.target.files);
            event.target.value = "";
          }}
        />
      </div>
      {current !== null && (
        <p role="status" className="flex items-center gap-2 text-sm text-subtle-foreground">
          <CircleNotchIcon className="size-4 animate-spin" aria-hidden="true" />
          {m.library_uploading({
            name: current.name,
            position: String(current.position),
            total: String(current.total),
          })}
        </p>
      )}
      {current === null && uploaded > 0 && (
        <p role="status" className="flex items-center gap-2 text-sm text-subtle-foreground">
          <CheckCircleIcon weight="fill" className="size-4 text-success" aria-hidden="true" />
          {m.library_uploaded({ count: String(uploaded) })}
        </p>
      )}
      {problems.length > 0 && (
        <ul role="alert" className="text-sm text-destructive">
          {problems.map((problem) => (
            <li key={problem.name}>{m.library_upload_failed(problem)}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
